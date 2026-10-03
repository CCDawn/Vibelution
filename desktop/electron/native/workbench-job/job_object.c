#define NAPI_VERSION 8
#include <node_api.h>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include <process.h>
#include <stdbool.h>

#define WORKBENCH_LOG_MAX_BYTES (64ULL * 1024ULL * 1024ULL)
#define WORKBENCH_LOG_BACKUPS 3
#define WORKBENCH_PIPE_BUFFER_BYTES (64 * 1024)
#define WORKBENCH_DRAIN_BUFFER_BYTES (32 * 1024)
#define WORKBENCH_ROTATE_ATTEMPTS 3
#define WORKBENCH_ROTATE_RETRY_MS 10
#define WORKBENCH_DRAIN_JOIN_MS 8000

typedef struct DrainState {
  volatile LONG references;
  HANDLE pipe;
  HANDLE thread;
  wchar_t *path;
  const char *stream_name;
  ULONGLONG max_bytes;
  volatile LONG done;
  volatile LONG error_code;
  volatile LONG64 dropped_bytes;
  volatile LONG rotations;
} DrainState;

typedef struct JobBox {
  HANDLE job;
  DrainState *stdout_drain;
  DrainState *stderr_drain;
} JobBox;

static void drain_release(DrainState *state) {
  if (state == NULL) return;
  if (InterlockedDecrement(&state->references) == 0) {
    free(state->path);
    free(state);
  }
}

static void record_drain_error(DrainState *state, DWORD error_code) {
  if (error_code == ERROR_SUCCESS) error_code = ERROR_WRITE_FAULT;
  InterlockedCompareExchange(&state->error_code, (LONG)error_code, 0);
}

static void add_dropped_bytes(DrainState *state, DWORD count) {
  if (count > 0) {
    InterlockedExchangeAdd64(&state->dropped_bytes, (LONG64)count);
  }
}

static wchar_t *backup_path(const wchar_t *path, int index) {
  const size_t base_length = wcslen(path);
  wchar_t suffix[16];
  size_t suffix_length;
  wchar_t *result;
  swprintf(suffix, sizeof(suffix) / sizeof(suffix[0]), L".%d", index);
  suffix_length = wcslen(suffix);
  result = (wchar_t *)calloc(base_length + suffix_length + 1, sizeof(wchar_t));
  if (result == NULL) return NULL;
  memcpy(result, path, base_length * sizeof(wchar_t));
  memcpy(result + base_length, suffix, (suffix_length + 1) * sizeof(wchar_t));
  return result;
}

static HANDLE open_log_file(const wchar_t *path, DWORD disposition) {
  return CreateFileW(
    path,
    GENERIC_READ | GENERIC_WRITE,
    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
    NULL,
    disposition,
    FILE_ATTRIBUTE_NORMAL,
    NULL);
}

static int trim_log_file(const wchar_t *path, ULONGLONG max_bytes, DWORD *error_code) {
  HANDLE file = open_log_file(path, OPEN_EXISTING);
  LARGE_INTEGER size;
  LARGE_INTEGER limit;
  if (file == INVALID_HANDLE_VALUE) {
    DWORD error = GetLastError();
    if (error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND) return 1;
    *error_code = error;
    return 0;
  }
  if (!GetFileSizeEx(file, &size)) {
    *error_code = GetLastError();
    CloseHandle(file);
    return 0;
  }
  if ((ULONGLONG)size.QuadPart > max_bytes) {
    unsigned char buffer[WORKBENCH_DRAIN_BUFFER_BYTES];
    LARGE_INTEGER source;
    LARGE_INTEGER destination;
    ULONGLONG remaining = max_bytes;
    source.QuadPart = size.QuadPart - (LONGLONG)max_bytes;
    destination.QuadPart = 0;
    while (remaining > 0) {
      DWORD chunk = remaining > sizeof(buffer) ? (DWORD)sizeof(buffer) : (DWORD)remaining;
      DWORD read_count = 0;
      DWORD written_offset = 0;
      if (!SetFilePointerEx(file, source, NULL, FILE_BEGIN)) {
        *error_code = GetLastError();
        CloseHandle(file);
        return 0;
      }
      if (!ReadFile(file, buffer, chunk, &read_count, NULL)) {
        *error_code = GetLastError();
        CloseHandle(file);
        return 0;
      }
      if (read_count != chunk) {
        *error_code = ERROR_HANDLE_EOF;
        CloseHandle(file);
        return 0;
      }
      if (!SetFilePointerEx(file, destination, NULL, FILE_BEGIN)) {
        *error_code = GetLastError();
        CloseHandle(file);
        return 0;
      }
      while (written_offset < chunk) {
        DWORD written = 0;
        if (!WriteFile(file, buffer + written_offset, chunk - written_offset, &written, NULL)
            || written == 0) {
          *error_code = GetLastError();
          if (*error_code == ERROR_SUCCESS) *error_code = ERROR_WRITE_FAULT;
          CloseHandle(file);
          return 0;
        }
        written_offset += written;
      }
      source.QuadPart += chunk;
      destination.QuadPart += chunk;
      remaining -= chunk;
    }
    limit.QuadPart = (LONGLONG)max_bytes;
    if (!SetFilePointerEx(file, limit, NULL, FILE_BEGIN) || !SetEndOfFile(file)) {
      *error_code = GetLastError();
      CloseHandle(file);
      return 0;
    }
  }
  CloseHandle(file);
  return 1;
}

static int move_log_file(const wchar_t *source, const wchar_t *destination, DWORD *error_code) {
  DWORD attributes = GetFileAttributesW(source);
  int attempt;
  if (attributes == INVALID_FILE_ATTRIBUTES) {
    DWORD error = GetLastError();
    if (error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND) return 1;
    *error_code = error;
    return 0;
  }
  for (attempt = 0; attempt < WORKBENCH_ROTATE_ATTEMPTS; attempt++) {
    if (MoveFileExW(source, destination, MOVEFILE_REPLACE_EXISTING)) return 1;
    *error_code = GetLastError();
    if (*error_code != ERROR_SHARING_VIOLATION
        && *error_code != ERROR_LOCK_VIOLATION
        && *error_code != ERROR_ACCESS_DENIED
        && *error_code != ERROR_BUSY) {
      return 0;
    }
    if (attempt + 1 < WORKBENCH_ROTATE_ATTEMPTS) Sleep(WORKBENCH_ROTATE_RETRY_MS);
  }
  return 0;
}

static int prepare_log(DrainState *state, HANDLE *file, ULONGLONG *file_bytes, DWORD *error_code) {
  int index;
  for (index = 0; index <= WORKBENCH_LOG_BACKUPS; index++) {
    wchar_t *target = index == 0 ? NULL : backup_path(state->path, index);
    const wchar_t *path = index == 0 ? state->path : target;
    int ok;
    if (path == NULL) {
      *error_code = ERROR_NOT_ENOUGH_MEMORY;
      return 0;
    }
    ok = trim_log_file(path, state->max_bytes, error_code);
    free(target);
    if (!ok) return 0;
  }
  *file = open_log_file(state->path, OPEN_ALWAYS);
  if (*file == INVALID_HANDLE_VALUE) {
    *error_code = GetLastError();
    *file = NULL;
    return 0;
  }
  {
    LARGE_INTEGER size;
    if (!GetFileSizeEx(*file, &size)) {
      *error_code = GetLastError();
      CloseHandle(*file);
      *file = NULL;
      return 0;
    }
    *file_bytes = size.QuadPart < 0 ? 0 : (ULONGLONG)size.QuadPart;
  }
  return 1;
}

static int rotate_log(DrainState *state, HANDLE *file, ULONGLONG *file_bytes, DWORD *error_code) {
  int index;
  if (*file != NULL) {
    CloseHandle(*file);
    *file = NULL;
  }
  for (index = WORKBENCH_LOG_BACKUPS - 1; index >= 1; index--) {
    wchar_t *source = backup_path(state->path, index);
    wchar_t *destination = backup_path(state->path, index + 1);
    int moved;
    if (source == NULL || destination == NULL) {
      free(source);
      free(destination);
      *error_code = ERROR_NOT_ENOUGH_MEMORY;
      return 0;
    }
    moved = move_log_file(source, destination, error_code);
    free(source);
    free(destination);
    if (!moved) return 0;
  }
  {
    wchar_t *first_backup = backup_path(state->path, 1);
    int moved;
    if (first_backup == NULL) {
      *error_code = ERROR_NOT_ENOUGH_MEMORY;
      return 0;
    }
    moved = move_log_file(state->path, first_backup, error_code);
    free(first_backup);
    if (!moved) return 0;
  }
  *file = open_log_file(state->path, CREATE_ALWAYS);
  if (*file == INVALID_HANDLE_VALUE) {
    *error_code = GetLastError();
    *file = NULL;
    return 0;
  }
  *file_bytes = 0;
  InterlockedIncrement(&state->rotations);
  return 1;
}

static int write_log_chunk(
  HANDLE file,
  const unsigned char *buffer,
  DWORD length,
  DWORD *written_count,
  DWORD *error_code) {
  LARGE_INTEGER end;
  DWORD offset = 0;
  *written_count = 0;
  end.QuadPart = 0;
  if (!SetFilePointerEx(file, end, NULL, FILE_END)) {
    *error_code = GetLastError();
    return 0;
  }
  while (offset < length) {
    DWORD written = 0;
    if (!WriteFile(file, buffer + offset, length - offset, &written, NULL) || written == 0) {
      *error_code = GetLastError();
      if (*error_code == ERROR_SUCCESS) *error_code = ERROR_WRITE_FAULT;
      *written_count = offset;
      return 0;
    }
    offset += written;
  }
  *written_count = offset;
  return 1;
}

static unsigned __stdcall drain_output(void *argument) {
  DrainState *state = (DrainState *)argument;
  unsigned char buffer[WORKBENCH_DRAIN_BUFFER_BYTES];
  HANDLE file = NULL;
  ULONGLONG file_bytes = 0;
  int sink_disabled = 0;
  DWORD error_code = ERROR_SUCCESS;
  if (!prepare_log(state, &file, &file_bytes, &error_code)) {
    record_drain_error(state, error_code);
    sink_disabled = 1;
  }
  while (state->pipe != NULL) {
    DWORD count = 0;
    if (!ReadFile(state->pipe, buffer, sizeof(buffer), &count, NULL) || count == 0) {
      DWORD error = GetLastError();
      if (error != ERROR_BROKEN_PIPE && error != ERROR_NO_DATA && error != ERROR_OPERATION_ABORTED) {
        record_drain_error(state, error);
      }
      break;
    }
    if (sink_disabled) {
      add_dropped_bytes(state, count);
      continue;
    }
    {
      DWORD offset = 0;
      while (offset < count) {
        ULONGLONG available;
        DWORD chunk = count - offset;
        DWORD written = 0;
        if (file_bytes >= state->max_bytes) {
          if (!rotate_log(state, &file, &file_bytes, &error_code)) {
            record_drain_error(state, error_code);
            sink_disabled = 1;
            add_dropped_bytes(state, count - offset);
            break;
          }
        }
        available = state->max_bytes - file_bytes;
        if ((ULONGLONG)chunk > available) chunk = (DWORD)available;
        if (chunk == 0 || !write_log_chunk(file, buffer + offset, chunk, &written, &error_code)) {
          if (chunk == 0 && error_code == ERROR_SUCCESS) error_code = ERROR_WRITE_FAULT;
          record_drain_error(state, error_code);
          sink_disabled = 1;
          add_dropped_bytes(state, count - offset - written);
          if (file != NULL) {
            CloseHandle(file);
            file = NULL;
          }
          break;
        }
        offset += chunk;
        file_bytes += chunk;
      }
    }
  }
  if (file != NULL) CloseHandle(file);
  if (state->pipe != NULL) {
    CloseHandle(state->pipe);
    state->pipe = NULL;
  }
  InterlockedExchange(&state->done, 1);
  drain_release(state);
  return 0;
}

static DrainState *start_drain(HANDLE pipe, wchar_t *path, const char *stream_name, ULONGLONG max_bytes) {
  DrainState *state = (DrainState *)calloc(1, sizeof(DrainState));
  uintptr_t thread;
  if (state == NULL) {
    if (pipe != NULL && pipe != INVALID_HANDLE_VALUE) CloseHandle(pipe);
    free(path);
    SetLastError(ERROR_NOT_ENOUGH_MEMORY);
    return NULL;
  }
  state->references = 2;
  state->pipe = pipe;
  state->path = path;
  state->stream_name = stream_name;
  state->max_bytes = max_bytes;
  thread = _beginthreadex(NULL, 0, drain_output, state, 0, NULL);
  if (thread == 0) {
    DWORD error = GetLastError();
    CloseHandle(pipe);
    state->pipe = NULL;
    state->references = 1;
    drain_release(state);
    SetLastError(error == ERROR_SUCCESS ? ERROR_NOT_ENOUGH_MEMORY : error);
    return NULL;
  }
  state->thread = (HANDLE)thread;
  return state;
}

static void release_drain_owner(DrainState **slot, int cancel) {
  DrainState *state = slot == NULL ? NULL : *slot;
  if (state == NULL) return;
  *slot = NULL;
  if (state->thread != NULL) {
    if (cancel && InterlockedCompareExchange(&state->done, 0, 0) == 0) {
      CancelSynchronousIo(state->thread);
      WaitForSingleObject(state->thread, WORKBENCH_DRAIN_JOIN_MS);
    }
    CloseHandle(state->thread);
    state->thread = NULL;
  }
  drain_release(state);
}

static void job_box_destroy(JobBox *box) {
  if (box == NULL) return;
  if (box->job != NULL) {
    TerminateJobObject(box->job, 1);
    CloseHandle(box->job);
    box->job = NULL;
  }
  release_drain_owner(&box->stdout_drain, 1);
  release_drain_owner(&box->stderr_drain, 1);
  free(box);
}

static void job_finalize(napi_env env, void *data, void *hint) {
  JobBox *box = (JobBox *)data;
  (void)env;
  (void)hint;
  job_box_destroy(box);
}

static napi_value throw_win(napi_env env, const char *what) {
  char message[256];
  snprintf(message, sizeof(message), "%s failed: %lu", what, GetLastError());
  napi_throw_error(env, NULL, message);
  return NULL;
}

static JobBox *unwrap_job(napi_env env, napi_value value) {
  JobBox *box = NULL;
  if (napi_get_value_external(env, value, (void **)&box) != napi_ok || box == NULL || box->job == NULL) {
    napi_throw_error(env, NULL, "workbench job handle is closed");
    return NULL;
  }
  return box;
}

static wchar_t *utf8_to_wide(napi_env env, const char *text) {
  int needed;
  wchar_t *wide;
  if (text == NULL) {
    text = "";
  }
  needed = MultiByteToWideChar(CP_UTF8, 0, text, -1, NULL, 0);
  if (needed <= 0) {
    napi_throw_error(env, NULL, "utf8 conversion failed");
    return NULL;
  }
  wide = (wchar_t *)calloc((size_t)needed, sizeof(wchar_t));
  if (wide == NULL) {
    napi_throw_error(env, NULL, "out of memory");
    return NULL;
  }
  if (MultiByteToWideChar(CP_UTF8, 0, text, -1, wide, needed) <= 0) {
    free(wide);
    napi_throw_error(env, NULL, "utf8 conversion failed");
    return NULL;
  }
  return wide;
}

static int ensure_wide(wchar_t **buffer, size_t *capacity, size_t needed) {
  wchar_t *next;
  if (needed <= *capacity) {
    return 1;
  }
  next = (wchar_t *)realloc(*buffer, needed * sizeof(wchar_t));
  if (next == NULL) {
    return 0;
  }
  *buffer = next;
  *capacity = needed;
  return 1;
}

static int append_wide(wchar_t **buffer, size_t *length, size_t *capacity, const wchar_t *text, size_t count) {
  if (!ensure_wide(buffer, capacity, *length + count + 1)) {
    return 0;
  }
  memcpy(*buffer + *length, text, count * sizeof(wchar_t));
  *length += count;
  (*buffer)[*length] = L'\0';
  return 1;
}

static int append_quoted_arg(wchar_t **buffer, size_t *length, size_t *capacity, const wchar_t *arg, int first) {
  const wchar_t *cursor;
  int quote = arg[0] == L'\0';
  if (!first && !append_wide(buffer, length, capacity, L" ", 1)) {
    return 0;
  }
  for (cursor = arg; *cursor != L'\0'; cursor++) {
    if (*cursor == L' ' || *cursor == L'\t' || *cursor == L'\n' || *cursor == L'\v' || *cursor == L'"') {
      quote = 1;
      break;
    }
  }
  if (!quote) {
    return append_wide(buffer, length, capacity, arg, wcslen(arg));
  }
  if (!append_wide(buffer, length, capacity, L"\"", 1)) {
    return 0;
  }
  cursor = arg;
  while (1) {
    unsigned backslashes = 0;
    while (*cursor == L'\\') {
      cursor++;
      backslashes++;
    }
    if (*cursor == L'\0') {
      unsigned index;
      for (index = 0; index < backslashes * 2; index++) {
        if (!append_wide(buffer, length, capacity, L"\\", 1)) {
          return 0;
        }
      }
      break;
    }
    if (*cursor == L'"') {
      unsigned index;
      for (index = 0; index < backslashes * 2 + 1; index++) {
        if (!append_wide(buffer, length, capacity, L"\\", 1)) {
          return 0;
        }
      }
      if (!append_wide(buffer, length, capacity, cursor, 1)) {
        return 0;
      }
    } else {
      unsigned index;
      for (index = 0; index < backslashes; index++) {
        if (!append_wide(buffer, length, capacity, L"\\", 1)) {
          return 0;
        }
      }
      if (!append_wide(buffer, length, capacity, cursor, 1)) {
        return 0;
      }
    }
    cursor++;
  }
  return append_wide(buffer, length, capacity, L"\"", 1);
}

static wchar_t *build_command_line(napi_env env, const wchar_t *executable, napi_value arguments) {
  uint32_t count = 0;
  uint32_t index;
  wchar_t *command = NULL;
  size_t length = 0;
  size_t capacity = 0;
  if (napi_get_array_length(env, arguments, &count) != napi_ok) {
    napi_throw_error(env, NULL, "arguments must be an array");
    return NULL;
  }
  if (!append_quoted_arg(&command, &length, &capacity, executable, 1)) {
    free(command);
    napi_throw_error(env, NULL, "out of memory");
    return NULL;
  }
  for (index = 0; index < count; index++) {
    napi_value item;
    char utf8[32768];
    size_t copied = 0;
    wchar_t *wide;
    napi_get_element(env, arguments, index, &item);
    if (napi_get_value_string_utf8(env, item, utf8, sizeof(utf8), &copied) != napi_ok) {
      free(command);
      napi_throw_error(env, NULL, "argument is not a string");
      return NULL;
    }
    wide = utf8_to_wide(env, utf8);
    if (wide == NULL) {
      free(command);
      return NULL;
    }
    if (!append_quoted_arg(&command, &length, &capacity, wide, 0)) {
      free(wide);
      free(command);
      napi_throw_error(env, NULL, "out of memory");
      return NULL;
    }
    free(wide);
  }
  return command;
}

static wchar_t *build_env_block(napi_env env, napi_value env_object) {
  napi_value names;
  uint32_t count = 0;
  uint32_t index;
  wchar_t *block = NULL;
  size_t length = 0;
  size_t capacity = 0;
  if (napi_get_property_names(env, env_object, &names) != napi_ok) {
    napi_throw_error(env, NULL, "env must be an object");
    return NULL;
  }
  if (napi_get_array_length(env, names, &count) != napi_ok) {
    napi_throw_error(env, NULL, "env must be an object");
    return NULL;
  }
  for (index = 0; index < count; index++) {
    napi_value key_value;
    napi_value item;
    char key_utf8[32768];
    char value_utf8[32768];
    size_t copied = 0;
    wchar_t *key = NULL;
    wchar_t *value = NULL;
    napi_get_element(env, names, index, &key_value);
    if (napi_get_value_string_utf8(env, key_value, key_utf8, sizeof(key_utf8), &copied) != napi_ok) {
      continue;
    }
    napi_get_named_property(env, env_object, key_utf8, &item);
    napi_valuetype kind;
    napi_typeof(env, item, &kind);
    if (kind == napi_undefined || kind == napi_null) {
      continue;
    }
    copied = 0;
    if (napi_get_value_string_utf8(env, item, value_utf8, sizeof(value_utf8), &copied) != napi_ok) {
      continue;
    }
    key = utf8_to_wide(env, key_utf8);
    value = utf8_to_wide(env, value_utf8);
    if (key == NULL || value == NULL) {
      free(key);
      free(value);
      free(block);
      return NULL;
    }
    if (!append_wide(&block, &length, &capacity, key, wcslen(key))
        || !append_wide(&block, &length, &capacity, L"=", 1)
        || !append_wide(&block, &length, &capacity, value, wcslen(value))
        || !append_wide(&block, &length, &capacity, L"\0", 1)) {
      free(key);
      free(value);
      free(block);
      napi_throw_error(env, NULL, "out of memory");
      return NULL;
    }
    free(key);
    free(value);
  }
  if (!append_wide(&block, &length, &capacity, L"\0", 1)) {
    free(block);
    napi_throw_error(env, NULL, "out of memory");
    return NULL;
  }
  return block;
}

static char *object_string(napi_env env, napi_value object, const char *name) {
  napi_value value;
  size_t length = 0;
  char *text;
  if (napi_get_named_property(env, object, name, &value) != napi_ok) {
    napi_throw_error(env, NULL, "missing spawn field");
    return NULL;
  }
  if (napi_get_value_string_utf8(env, value, NULL, 0, &length) != napi_ok) {
    napi_throw_error(env, NULL, "spawn field is not a string");
    return NULL;
  }
  text = (char *)calloc(length + 1, 1);
  if (text == NULL) {
    napi_throw_error(env, NULL, "out of memory");
    return NULL;
  }
  if (napi_get_value_string_utf8(env, value, text, length + 1, &length) != napi_ok) {
    free(text);
    napi_throw_error(env, NULL, "spawn field is not a string");
    return NULL;
  }
  return text;
}

static ULONGLONG optional_log_max_bytes(napi_env env, napi_value object) {
  napi_value value;
  napi_valuetype type;
  double bytes;
  {
    bool has_property = false;
    if (napi_has_named_property(env, object, "maxLogBytes", &has_property) != napi_ok || !has_property) {
      return WORKBENCH_LOG_MAX_BYTES;
    }
  }
  if (napi_get_named_property(env, object, "maxLogBytes", &value) != napi_ok
      || napi_typeof(env, value, &type) != napi_ok
      || type != napi_number
      || napi_get_value_double(env, value, &bytes) != napi_ok
      || bytes < WORKBENCH_DRAIN_BUFFER_BYTES
      || bytes > 1024.0 * 1024.0 * 1024.0
      || bytes != bytes) {
    napi_throw_type_error(env, NULL, "maxLogBytes must be a number between 32 KiB and 1 GiB");
    return 0;
  }
  return (ULONGLONG)bytes;
}

static HANDLE open_inheritable(const wchar_t *path, DWORD access, DWORD disposition) {
  SECURITY_ATTRIBUTES attributes;
  ZeroMemory(&attributes, sizeof(attributes));
  attributes.nLength = sizeof(attributes);
  attributes.bInheritHandle = TRUE;
  return CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, &attributes, disposition, FILE_ATTRIBUTE_NORMAL, NULL);
}

static napi_value job_external(napi_env env, JobBox *box) {
  napi_value external;
  if (box == NULL) {
    napi_throw_error(env, NULL, "out of memory");
    return NULL;
  }
  if (napi_create_external(env, box, job_finalize, NULL, &external) != napi_ok) {
    job_box_destroy(box);
    napi_throw_error(env, NULL, "could not retain job handle");
    return NULL;
  }
  return external;
}

static napi_value spawn(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_value arguments;
  napi_value env_object;
  napi_value result;
  char *executable_utf8 = NULL;
  char *cwd_utf8 = NULL;
  char *stdout_utf8 = NULL;
  char *stderr_utf8 = NULL;
  wchar_t *executable = NULL;
  wchar_t *cwd = NULL;
  wchar_t *stdout_path = NULL;
  wchar_t *stderr_path = NULL;
  wchar_t *command = NULL;
  wchar_t *env_block = NULL;
  HANDLE job = NULL;
  HANDLE stdin_handle = NULL;
  HANDLE stdout_read = NULL;
  HANDLE stdout_write = NULL;
  HANDLE stderr_read = NULL;
  HANDLE stderr_write = NULL;
  HANDLE inherited[3];
  JobBox *box = NULL;
  STARTUPINFOEXW startup;
  PROCESS_INFORMATION process;
  SIZE_T attribute_size = 0;
  JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits;
  SECURITY_ATTRIBUTES pipe_security;
  ULONGLONG max_log_bytes;
  DWORD creation_flags;
  ZeroMemory(&startup, sizeof(startup));
  ZeroMemory(&process, sizeof(process));
  napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  if (argc < 1) {
    napi_throw_error(env, NULL, "spawn input is required");
    return NULL;
  }
  executable_utf8 = object_string(env, argv[0], "executable");
  cwd_utf8 = object_string(env, argv[0], "cwd");
  stdout_utf8 = object_string(env, argv[0], "stdoutPath");
  stderr_utf8 = object_string(env, argv[0], "stderrPath");
  if (executable_utf8 == NULL || cwd_utf8 == NULL || stdout_utf8 == NULL || stderr_utf8 == NULL) {
    goto cleanup_inputs;
  }
  if (napi_get_named_property(env, argv[0], "arguments", &arguments) != napi_ok
      || napi_get_named_property(env, argv[0], "env", &env_object) != napi_ok) {
    napi_throw_error(env, NULL, "spawn input is incomplete");
    goto cleanup_inputs;
  }
  max_log_bytes = optional_log_max_bytes(env, argv[0]);
  if (max_log_bytes == 0) goto cleanup_inputs;
  executable = utf8_to_wide(env, executable_utf8);
  cwd = utf8_to_wide(env, cwd_utf8);
  stdout_path = utf8_to_wide(env, stdout_utf8);
  stderr_path = utf8_to_wide(env, stderr_utf8);
  if (executable == NULL || cwd == NULL || stdout_path == NULL || stderr_path == NULL) {
    goto cleanup_inputs;
  }
  command = build_command_line(env, executable, arguments);
  env_block = build_env_block(env, env_object);
  if (command == NULL || env_block == NULL) {
    goto cleanup_inputs;
  }

  job = CreateJobObjectW(NULL, NULL);
  if (job == NULL) {
    throw_win(env, "CreateJobObjectW");
    goto cleanup_inputs;
  }
  ZeroMemory(&limits, sizeof(limits));
  limits.BasicLimitInformation.LimitFlags =
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK;
  if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) {
    throw_win(env, "SetInformationJobObject");
    goto cleanup_job;
  }

  stdin_handle = open_inheritable(L"\\\\.\\NUL", GENERIC_READ, OPEN_EXISTING);
  if (stdin_handle == INVALID_HANDLE_VALUE) {
    throw_win(env, "CreateFileW(stdin)");
    goto cleanup_stdio;
  }
  ZeroMemory(&pipe_security, sizeof(pipe_security));
  pipe_security.nLength = sizeof(pipe_security);
  pipe_security.bInheritHandle = TRUE;
  if (!CreatePipe(&stdout_read, &stdout_write, &pipe_security, WORKBENCH_PIPE_BUFFER_BYTES)
      || !SetHandleInformation(stdout_read, HANDLE_FLAG_INHERIT, 0)) {
    throw_win(env, "CreatePipe(stdout)");
    goto cleanup_stdio;
  }
  if (!CreatePipe(&stderr_read, &stderr_write, &pipe_security, WORKBENCH_PIPE_BUFFER_BYTES)
      || !SetHandleInformation(stderr_read, HANDLE_FLAG_INHERIT, 0)) {
    throw_win(env, "CreatePipe(stderr)");
    goto cleanup_stdio;
  }

  InitializeProcThreadAttributeList(NULL, 1, 0, &attribute_size);
  startup.lpAttributeList = (LPPROC_THREAD_ATTRIBUTE_LIST)malloc(attribute_size);
  if (startup.lpAttributeList == NULL) {
    napi_throw_error(env, NULL, "out of memory");
    goto cleanup_stdio;
  }
  if (!InitializeProcThreadAttributeList(startup.lpAttributeList, 1, 0, &attribute_size)) {
    free(startup.lpAttributeList);
    startup.lpAttributeList = NULL;
    throw_win(env, "InitializeProcThreadAttributeList");
    goto cleanup_stdio;
  }
  inherited[0] = stdin_handle;
  inherited[1] = stdout_write;
  inherited[2] = stderr_write;
  if (!UpdateProcThreadAttribute(
        startup.lpAttributeList,
        0,
        PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        inherited,
        sizeof(inherited),
        NULL,
        NULL)) {
    throw_win(env, "UpdateProcThreadAttribute");
    goto cleanup_attributes;
  }
  startup.StartupInfo.cb = sizeof(startup);
  startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
  startup.StartupInfo.hStdInput = stdin_handle;
  startup.StartupInfo.hStdOutput = stdout_write;
  startup.StartupInfo.hStdError = stderr_write;
  creation_flags = CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT;
  if (!CreateProcessW(
        executable,
        command,
        NULL,
        NULL,
        TRUE,
        creation_flags,
        env_block,
        cwd,
        &startup.StartupInfo,
        &process)) {
    throw_win(env, "CreateProcessW");
    goto cleanup_attributes;
  }
  if (!AssignProcessToJobObject(job, process.hProcess)) {
    throw_win(env, "AssignProcessToJobObject");
    TerminateProcess(process.hProcess, 1);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    goto cleanup_attributes;
  }
  box = (JobBox *)calloc(1, sizeof(JobBox));
  if (box == NULL) {
    napi_throw_error(env, NULL, "out of memory");
    TerminateJobObject(job, 1);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    goto cleanup_attributes;
  }
  box->job = job;
  job = NULL;
  {
    HANDLE pipe = stdout_read;
    wchar_t *path = stdout_path;
    stdout_read = NULL;
    stdout_path = NULL;
    box->stdout_drain = start_drain(pipe, path, "stdout", max_log_bytes);
    if (box->stdout_drain == NULL) {
      throw_win(env, "CreateThread(stdout drain)");
      TerminateJobObject(box->job, 1);
      CloseHandle(process.hThread);
      CloseHandle(process.hProcess);
      goto cleanup_box;
    }
  }
  {
    HANDLE pipe = stderr_read;
    wchar_t *path = stderr_path;
    stderr_read = NULL;
    stderr_path = NULL;
    box->stderr_drain = start_drain(pipe, path, "stderr", max_log_bytes);
    if (box->stderr_drain == NULL) {
      throw_win(env, "CreateThread(stderr drain)");
      TerminateJobObject(box->job, 1);
      CloseHandle(process.hThread);
      CloseHandle(process.hProcess);
      goto cleanup_box;
    }
  }
  CloseHandle(stdout_write);
  stdout_write = NULL;
  CloseHandle(stderr_write);
  stderr_write = NULL;
  if (ResumeThread(process.hThread) == (DWORD)-1) {
    throw_win(env, "ResumeThread");
    TerminateJobObject(box->job, 1);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    goto cleanup_box;
  }
  CloseHandle(process.hThread);
  CloseHandle(process.hProcess);
  DeleteProcThreadAttributeList(startup.lpAttributeList);
  free(startup.lpAttributeList);
  startup.lpAttributeList = NULL;
  CloseHandle(stdin_handle);
  stdin_handle = NULL;
  free(executable_utf8);
  free(cwd_utf8);
  free(stdout_utf8);
  free(stderr_utf8);
  free(executable);
  free(cwd);
  free(command);
  free(env_block);

  result = job_external(env, box);
  box = NULL;
  if (result == NULL) {
    return NULL;
  }
  {
    napi_value pid_value;
    napi_value wrapper;
    napi_create_object(env, &wrapper);
    napi_create_int32(env, (int32_t)process.dwProcessId, &pid_value);
    napi_set_named_property(env, wrapper, "pid", pid_value);
    napi_set_named_property(env, wrapper, "job", result);
    return wrapper;
  }

cleanup_attributes:
  if (startup.lpAttributeList != NULL) {
    DeleteProcThreadAttributeList(startup.lpAttributeList);
    free(startup.lpAttributeList);
    startup.lpAttributeList = NULL;
  }
cleanup_stdio:
  if (stdin_handle != NULL && stdin_handle != INVALID_HANDLE_VALUE) CloseHandle(stdin_handle);
  if (stdout_read != NULL && stdout_read != INVALID_HANDLE_VALUE) CloseHandle(stdout_read);
  if (stdout_write != NULL && stdout_write != INVALID_HANDLE_VALUE) CloseHandle(stdout_write);
  if (stderr_read != NULL && stderr_read != INVALID_HANDLE_VALUE) CloseHandle(stderr_read);
  if (stderr_write != NULL && stderr_write != INVALID_HANDLE_VALUE) CloseHandle(stderr_write);
cleanup_job:
  if (job != NULL) CloseHandle(job);
cleanup_inputs:
  free(executable_utf8);
  free(cwd_utf8);
  free(stdout_utf8);
  free(stderr_utf8);
  free(executable);
  free(cwd);
  free(stdout_path);
  free(stderr_path);
  free(command);
  free(env_block);
  return NULL;

cleanup_box:
  if (stdout_write != NULL && stdout_write != INVALID_HANDLE_VALUE) {
    CloseHandle(stdout_write);
    stdout_write = NULL;
  }
  if (stderr_write != NULL && stderr_write != INVALID_HANDLE_VALUE) {
    CloseHandle(stderr_write);
    stderr_write = NULL;
  }
  job_box_destroy(box);
  box = NULL;
  goto cleanup_attributes;
}

static napi_value terminate(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  JobBox *box;
  napi_value result;
  napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  box = unwrap_job(env, argv[0]);
  if (box == NULL) {
    return NULL;
  }
  if (!TerminateJobObject(box->job, 1)) {
    return throw_win(env, "TerminateJobObject");
  }
  napi_get_boolean(env, 1, &result);
  return result;
}

static napi_value active_count(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  JobBox *box;
  JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting;
  napi_value result;
  napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  box = unwrap_job(env, argv[0]);
  if (box == NULL) {
    return NULL;
  }
  ZeroMemory(&accounting, sizeof(accounting));
  if (!QueryInformationJobObject(box->job, JobObjectBasicAccountingInformation, &accounting, sizeof(accounting), NULL)) {
    return throw_win(env, "QueryInformationJobObject");
  }
  napi_create_uint32(env, accounting.ActiveProcesses, &result);
  return result;
}

static int query_active_processes(JobBox *box, DWORD *count) {
  JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting;
  ZeroMemory(&accounting, sizeof(accounting));
  if (!QueryInformationJobObject(box->job, JobObjectBasicAccountingInformation, &accounting, sizeof(accounting), NULL)) {
    return 0;
  }
  *count = accounting.ActiveProcesses;
  return 1;
}

static int drain_is_complete(DrainState *state) {
  if (state == NULL) return 1;
  if (InterlockedCompareExchange(&state->done, 0, 0) == 0 || state->thread == NULL) return 0;
  return WaitForSingleObject(state->thread, 0) == WAIT_OBJECT_0;
}

static int all_drains_complete(JobBox *box) {
  return drain_is_complete(box->stdout_drain) && drain_is_complete(box->stderr_drain);
}

static int set_named_number(napi_env env, napi_value object, const char *name, double number) {
  napi_value value;
  return napi_create_double(env, number, &value) == napi_ok
    && napi_set_named_property(env, object, name, value) == napi_ok;
}

static int set_drain_channel(napi_env env, napi_value item, DrainState *state) {
  napi_value stream;
  napi_value complete;
  if (state == NULL) return 0;
  if (napi_create_string_utf8(env, state->stream_name, NAPI_AUTO_LENGTH, &stream) != napi_ok
      || napi_set_named_property(env, item, "stream", stream) != napi_ok
      || napi_get_boolean(env, drain_is_complete(state), &complete) != napi_ok
      || napi_set_named_property(env, item, "complete", complete) != napi_ok
      || !set_named_number(env, item, "errorCode", (double)InterlockedCompareExchange(&state->error_code, 0, 0))
      || !set_named_number(env, item, "droppedBytes", (double)InterlockedCompareExchange64(&state->dropped_bytes, 0, 0))
      || !set_named_number(env, item, "rotations", (double)InterlockedCompareExchange(&state->rotations, 0, 0))) {
    return 0;
  }
  return 1;
}

static napi_value drain_status(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_value result;
  napi_value channels;
  napi_value item;
  napi_value complete;
  JobBox *box;
  napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  box = unwrap_job(env, argv[0]);
  if (box == NULL) return NULL;
  if (napi_create_object(env, &result) != napi_ok
      || napi_create_array_with_length(env, 2, &channels) != napi_ok) {
    napi_throw_error(env, NULL, "could not create workbench drain status");
    return NULL;
  }
  if (napi_create_object(env, &item) != napi_ok || !set_drain_channel(env, item, box->stdout_drain)
      || napi_set_element(env, channels, 0, item) != napi_ok
      || napi_create_object(env, &item) != napi_ok || !set_drain_channel(env, item, box->stderr_drain)
      || napi_set_element(env, channels, 1, item) != napi_ok
      || napi_get_boolean(env, all_drains_complete(box), &complete) != napi_ok
      || napi_set_named_property(env, result, "complete", complete) != napi_ok
      || napi_set_named_property(env, result, "channels", channels) != napi_ok) {
    napi_throw_error(env, NULL, "could not read workbench drain status");
    return NULL;
  }
  return result;
}

static napi_value close_job(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  JobBox *box;
  napi_value result;
  DWORD active_processes = 0;
  napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  box = unwrap_job(env, argv[0]);
  if (box == NULL) {
    return NULL;
  }
  if (!query_active_processes(box, &active_processes)) {
    return throw_win(env, "QueryInformationJobObject");
  }
  if (active_processes != 0 || !all_drains_complete(box)) {
    napi_throw_error(env, NULL, "workbench job cannot close until processes and stdout/stderr drains exit");
    return NULL;
  }
  if (!CloseHandle(box->job)) {
    return throw_win(env, "CloseHandle(job)");
  }
  box->job = NULL;
  release_drain_owner(&box->stdout_drain, 0);
  release_drain_owner(&box->stderr_drain, 0);
  napi_get_undefined(env, &result);
  return result;
}

static napi_value init(napi_env env, napi_value exports) {
  napi_value fn;
  napi_create_function(env, "spawn", NAPI_AUTO_LENGTH, spawn, NULL, &fn);
  napi_set_named_property(env, exports, "spawn", fn);
  napi_create_function(env, "terminate", NAPI_AUTO_LENGTH, terminate, NULL, &fn);
  napi_set_named_property(env, exports, "terminate", fn);
  napi_create_function(env, "activeCount", NAPI_AUTO_LENGTH, active_count, NULL, &fn);
  napi_set_named_property(env, exports, "activeCount", fn);
  napi_create_function(env, "drainStatus", NAPI_AUTO_LENGTH, drain_status, NULL, &fn);
  napi_set_named_property(env, exports, "drainStatus", fn);
  napi_create_function(env, "close", NAPI_AUTO_LENGTH, close_job, NULL, &fn);
  napi_set_named_property(env, exports, "close", fn);
  return exports;
}

NAPI_MODULE(NODE_GYP_MODULE_NAME, init)
