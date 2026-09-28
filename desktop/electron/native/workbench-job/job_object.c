#define NAPI_VERSION 8
#include <node_api.h>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <stdlib.h>
#include <string.h>
#include <stdio.h>

typedef struct JobBox {
  HANDLE job;
} JobBox;

static void job_finalize(napi_env env, void *data, void *hint) {
  JobBox *box = (JobBox *)data;
  (void)env;
  (void)hint;
  if (box == NULL) {
    return;
  }
  if (box->job != NULL) {
    CloseHandle(box->job);
    box->job = NULL;
  }
  free(box);
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

static HANDLE open_inheritable(const wchar_t *path, DWORD access, DWORD disposition) {
  SECURITY_ATTRIBUTES attributes;
  ZeroMemory(&attributes, sizeof(attributes));
  attributes.nLength = sizeof(attributes);
  attributes.bInheritHandle = TRUE;
  return CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, &attributes, disposition, FILE_ATTRIBUTE_NORMAL, NULL);
}

static napi_value job_external(napi_env env, HANDLE job) {
  JobBox *box = (JobBox *)calloc(1, sizeof(JobBox));
  napi_value external;
  if (box == NULL) {
    CloseHandle(job);
    napi_throw_error(env, NULL, "out of memory");
    return NULL;
  }
  box->job = job;
  if (napi_create_external(env, box, job_finalize, NULL, &external) != napi_ok) {
    CloseHandle(job);
    free(box);
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
  HANDLE stdout_handle = NULL;
  HANDLE stderr_handle = NULL;
  HANDLE inherited[3];
  STARTUPINFOEXW startup;
  PROCESS_INFORMATION process;
  SIZE_T attribute_size = 0;
  JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits;
  DWORD creation_flags;
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
  stdout_handle = open_inheritable(stdout_path, FILE_APPEND_DATA, OPEN_ALWAYS);
  stderr_handle = open_inheritable(stderr_path, FILE_APPEND_DATA, OPEN_ALWAYS);
  if (stdin_handle == INVALID_HANDLE_VALUE || stdout_handle == INVALID_HANDLE_VALUE || stderr_handle == INVALID_HANDLE_VALUE) {
    throw_win(env, "CreateFileW");
    goto cleanup_stdio;
  }

  ZeroMemory(&startup, sizeof(startup));
  ZeroMemory(&process, sizeof(process));
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
  inherited[1] = stdout_handle;
  inherited[2] = stderr_handle;
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
  startup.StartupInfo.hStdOutput = stdout_handle;
  startup.StartupInfo.hStdError = stderr_handle;
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
  if (ResumeThread(process.hThread) == (DWORD)-1) {
    throw_win(env, "ResumeThread");
    TerminateJobObject(job, 1);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    goto cleanup_attributes;
  }
  CloseHandle(process.hThread);
  CloseHandle(process.hProcess);
  DeleteProcThreadAttributeList(startup.lpAttributeList);
  free(startup.lpAttributeList);
  CloseHandle(stdin_handle);
  CloseHandle(stdout_handle);
  CloseHandle(stderr_handle);
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

  result = job_external(env, job);
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
  }
cleanup_stdio:
  if (stdin_handle != NULL && stdin_handle != INVALID_HANDLE_VALUE) CloseHandle(stdin_handle);
  if (stdout_handle != NULL && stdout_handle != INVALID_HANDLE_VALUE) CloseHandle(stdout_handle);
  if (stderr_handle != NULL && stderr_handle != INVALID_HANDLE_VALUE) CloseHandle(stderr_handle);
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

static napi_value close_job(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  JobBox *box;
  napi_value result;
  napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  box = unwrap_job(env, argv[0]);
  if (box == NULL) {
    return NULL;
  }
  CloseHandle(box->job);
  box->job = NULL;
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
  napi_create_function(env, "close", NAPI_AUTO_LENGTH, close_job, NULL, &fn);
  napi_set_named_property(env, exports, "close", fn);
  return exports;
}

NAPI_MODULE(NODE_GYP_MODULE_NAME, init)
