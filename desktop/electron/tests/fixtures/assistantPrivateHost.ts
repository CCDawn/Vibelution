export const CHILD = String.raw`
import argparse,json,os,socket,sys
from pathlib import Path
sys.path.insert(0,os.environ["SYNTHETIC_SOURCE_ROOT"])
parser=argparse.ArgumentParser()
for name in ("profile-root","runtime-dir","instance-id","projects-file"):parser.add_argument("--"+name,required=True)
args=parser.parse_args()
token=os.environ.pop("VIBELUTION_ASSISTANT_TOKEN")
assert os.environ.pop("VIBELUTION_ASSISTANT_MAIN_CONTROL")=="1"
appearance_enabled=os.environ.pop("VIBELUTION_ASSISTANT_APPEARANCE_CONTROL","")=="1"
os.environ["VIBELUTION_PROCESS_ROLE"]="launcher_assistant"
os.environ["VIBELUTION_ASSISTANT_NATIVE_ROOT"]=args.profile_root
from core.assistant_runtime.host import create_app
from core.assistant_runtime.main_control import MainControlBroker
from core.assistant_runtime.actions import execute_action
from core.infrastructure.atomic_io import atomic_write_json
import uvicorn
projects=json.loads(Path(args.projects_file).read_text())["projects"]
class Dispatch:
 def project_ids(self):return tuple(projects)
 async def heartbeat(self):pass
class Native:
 def bootstrap(self):return self.identity()
 def identity(self):return {"assistant":{"agentId":"synthetic-agent","directSessionId":"synthetic-session"}}
 def shutdown(self):pass
 def submit(self,message,request_id):
  payload=json.loads(message)
  assert set(payload)=={"action","parameters"}
  return execute_action(payload["action"],payload["parameters"],runtime={"agentId":"synthetic-agent","sessionId":"synthetic-session","turnId":request_id},governed=True)
dispatch=Dispatch()
broker=MainControlBroker(dispatch.project_ids,appearance_enabled=appearance_enabled)
sock=socket.socket();sock.bind(("127.0.0.1",0))
def ready():atomic_write_json(Path(args.runtime_dir)/"ready.json",{"protocolVersion":1,"role":"launcher_assistant","instanceId":args.instance_id,"pid":os.getpid(),"port":sock.getsockname()[1]},strict_replace=True)
def stop():server.should_exit=True
app=create_app(native=Native(),token=token,dispatch=dispatch,main_control=broker,on_ready=ready,on_shutdown=stop)
server=uvicorn.Server(uvicorn.Config(app,access_log=False,log_level="warning",timeout_graceful_shutdown=2))
try:server.run(sockets=[sock])
finally:sock.close()
`;
