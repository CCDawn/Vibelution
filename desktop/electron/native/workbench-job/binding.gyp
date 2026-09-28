{
  "targets": [
    {
      "target_name": "workbench_job",
      "defines": ["NAPI_VERSION=8"],
      "conditions": [
        ["OS=='win'", {
          "sources": ["job_object.c"]
        }, {
          "sources": ["job_object_stub.c"]
        }]
      ]
    }
  ]
}
