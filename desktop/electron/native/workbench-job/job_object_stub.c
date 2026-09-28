#define NAPI_VERSION 8
#include <node_api.h>

static napi_value unsupported(napi_env env, napi_callback_info info) {
  (void)info;
  napi_throw_error(env, NULL, "workbench job objects are only available on Windows");
  return NULL;
}

static napi_value init(napi_env env, napi_value exports) {
  napi_value fn;
  napi_create_function(env, "spawn", NAPI_AUTO_LENGTH, unsupported, NULL, &fn);
  napi_set_named_property(env, exports, "spawn", fn);
  napi_create_function(env, "terminate", NAPI_AUTO_LENGTH, unsupported, NULL, &fn);
  napi_set_named_property(env, exports, "terminate", fn);
  napi_create_function(env, "activeCount", NAPI_AUTO_LENGTH, unsupported, NULL, &fn);
  napi_set_named_property(env, exports, "activeCount", fn);
  napi_create_function(env, "close", NAPI_AUTO_LENGTH, unsupported, NULL, &fn);
  napi_set_named_property(env, exports, "close", fn);
  return exports;
}

NAPI_MODULE(NODE_GYP_MODULE_NAME, init)
