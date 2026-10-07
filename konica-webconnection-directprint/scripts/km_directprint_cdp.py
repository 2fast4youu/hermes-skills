#!/usr/bin/env python3
"""
Konica Minolta Web Connection Direct Print automation (tested on bizhub C3350i).
Default is DRY RUN. Add --execute to actually click OK and submit the print job.
"""
import argparse, asyncio, itertools, json, os, shutil, socket, subprocess, sys, tempfile, time
import requests, websockets

DEFAULT_URL = os.environ.get("KM_WCD_URL", "https://192.168.1.50/wcd/spa_main.html")
DEFAULT_CHROME = "/snap/bin/chromium"
SUPPORTED_EXT = {"pdf","tif","tiff","pcl","txt","ps","jpg","jpeg","xps","docx","xlsx","pptx","zip","ppml","vdx"}


def wait_port(port, timeout=12):
    deadline=time.time()+timeout
    while time.time()<deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4): return True
        except OSError:
            time.sleep(0.2)
    return False


def free_port():
    s=socket.socket(); s.bind(("127.0.0.1",0)); p=s.getsockname()[1]; s.close(); return p


class CDP:
    def __init__(self, ws):
        self.ws=ws; self.idc=itertools.count(1); self.pending={}; self.contexts={}; self.requests=[]; self.responses=[]
    async def recv(self):
        async for msg in self.ws:
            d=json.loads(msg)
            if "id" in d and d["id"] in self.pending:
                self.pending.pop(d["id"]).set_result(d)
            else:
                if d.get("method")=="Runtime.executionContextCreated":
                    c=d["params"]["context"]; self.contexts[c["id"]]=c
                elif d.get("method")=="Network.requestWillBeSent":
                    r=d["params"]["request"]; self.requests.append({"method":r.get("method"),"url":r.get("url"),"postData":r.get("postData","")})
                elif d.get("method")=="Network.responseReceived":
                    r=d["params"]["response"]; self.responses.append({"status":r.get("status"),"url":r.get("url")})
    async def call(self, method, params=None, timeout=60):
        i=next(self.idc); fut=asyncio.get_event_loop().create_future(); self.pending[i]=fut
        await self.ws.send(json.dumps({"id":i,"method":method,"params":params or {}}))
        res=await asyncio.wait_for(fut, timeout)
        if "error" in res:
            raise RuntimeError(f"CDP {method} failed: {res['error']}")
        return res
    async def eval(self, expression, context_id=None, by_value=True, timeout=60):
        p={"expression":expression,"returnByValue":by_value}
        if context_id: p["contextId"]=context_id
        return await self.call("Runtime.evaluate", p, timeout=timeout)


async def automate(args):
    path=os.path.abspath(args.file)
    if not os.path.isfile(path):
        raise SystemExit(f"File not found: {path}")
    ext=path.rsplit('.',1)[-1].lower() if '.' in path else ''
    if ext not in SUPPORTED_EXT:
        raise SystemExit(f"Unsupported extension .{ext}. Supported: {', '.join(sorted(SUPPORTED_EXT))}")
    chrome=args.chrome or DEFAULT_CHROME
    if not os.path.exists(chrome):
        chrome=shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome") or chrome
    port=args.port or free_port()
    user_data=tempfile.mkdtemp(prefix="km-directprint-chrome-")
    proc=subprocess.Popen([chrome,"--headless=new","--ignore-certificate-errors","--disable-gpu","--no-sandbox",f"--remote-debugging-port={port}",f"--user-data-dir={user_data}","about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_port(port):
            raise RuntimeError("Chromium CDP port did not open")
        wsurl=requests.put(f"http://127.0.0.1:{port}/json/new?about:blank", timeout=5).json()["webSocketDebuggerUrl"]
        async with websockets.connect(wsurl, max_size=50_000_000) as ws:
            cdp=CDP(ws); asyncio.create_task(cdp.recv())
            for m in ["Page.enable","Runtime.enable","Network.enable","DOM.enable"]:
                await cdp.call(m)
            await cdp.call("Page.navigate", {"url":args.url})
            await asyncio.sleep(args.initial_wait)
            await cdp.eval("""(()=>{let f=document.getElementById('SPA-contents-body'); let d=f&&f.contentWindow&&f.contentWindow.document; let b=d&&d.getElementById('ID_LGI_LOGIN_BT'); if(b){b.click(); return 'clicked-login';} return 'no-login-button';})()""")
            await asyncio.sleep(args.login_wait)
            await cdp.eval("spa_load_contents('013_000_DIP000')")
            await asyncio.sleep(args.page_wait)
            frame_ctx=None
            for cid in list(cdp.contexts.keys()):
                try:
                    res=await cdp.eval('!!document.getElementById("P7_F_FI") && document.body.innerText.slice(0,100)', cid)
                    if res["result"]["result"].get("value"):
                        frame_ctx=cid; break
                except Exception:
                    pass
            if not frame_ctx:
                raise RuntimeError("Direct-print iframe/input P7_F_FI not found")
            obj=(await cdp.eval('document.getElementById("P7_F_FI")', frame_ctx, by_value=False))["result"]["result"]["objectId"]
            await cdp.call("DOM.setFileInputFiles", {"objectId":obj, "files":[path]})
            info=(await cdp.eval('(()=>{let f=document.getElementById("P7_F_FI"); return {len:f.files.length,name:f.files[0]&&f.files[0].name,value:f.value,token:document.getElementById("h_tkn_p")&&document.getElementById("h_tkn_p").value};})()', frame_ctx))["result"]["result"].get("value")
            if not info or info.get("len") != 1:
                raise RuntimeError(f"File input not set: {info}")
            copies=max(1, int(args.copies))
            await cdp.eval(f'document.getElementById("ID_P_PRI_BPN").value = "{copies}"', frame_ctx)
            if args.duplex:
                await cdp.eval('document.getElementById("ID_P_PRI_BDL").value = "Duplex"', frame_ctx)
            if args.tray:
                await cdp.eval(f'document.getElementById("ID_P_PRI_BTR").value = {json.dumps(args.tray)}', frame_ctx)
            print(json.dumps({"ready":True,"file":path,"filename":info.get("name"),"copies":copies,"duplex":bool(args.duplex),"tray":args.tray or "Auto","execute":bool(args.execute)}, ensure_ascii=False))
            if not args.execute:
                print("DRY_RUN_ONLY: add --execute to actually submit the print job")
                return
            await cdp.eval('document.getElementById("ID_OK_P_PRI_SET").click()', frame_ctx)
            deadline=time.time()+args.result_timeout; last_text=""
            while time.time()<deadline:
                await asyncio.sleep(2)
                try:
                    last_text=(await cdp.eval('document.body.innerText.slice(0,2000)', frame_ctx))["result"]["result"].get("value","")
                except Exception:
                    pass
                joined="\n".join([r.get("url","") for r in cdp.requests+cdp.responses])
                if "result.html" in joined or "UpdatePrintExecuteFlgByCgi" in joined or "DirectPrintOk" in last_text:
                    print(json.dumps({"submitted":True,"observed_result_signal":True,"text":last_text[-1000:]}, ensure_ascii=False))
                    return
            print(json.dumps({"submitted":True,"observed_result_signal":False,"last_text":last_text[-1000:],"requests":[r for r in cdp.requests if any(x in r.get('url','') for x in ['i_file.cgi','user.cgi','result.html','UpdatePrintExecuteFlgByCgi'])]}, ensure_ascii=False))
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
        shutil.rmtree(user_data, ignore_errors=True)


def main():
    ap=argparse.ArgumentParser(description="Print a local file through Konica Minolta Web Connection Direct Print")
    ap.add_argument("file")
    ap.add_argument("--execute", action="store_true", help="actually click OK and submit the print job; default is dry run")
    ap.add_argument("--copies", type=int, default=1)
    ap.add_argument("--duplex", action="store_true", help="set duplex; leave off for one-sided/default")
    ap.add_argument("--tray", help="paper tray value, default Auto")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--chrome", default=DEFAULT_CHROME)
    ap.add_argument("--port", type=int)
    ap.add_argument("--initial-wait", type=float, default=8)
    ap.add_argument("--login-wait", type=float, default=10)
    ap.add_argument("--page-wait", type=float, default=8)
    ap.add_argument("--result-timeout", type=float, default=60)
    args=ap.parse_args()
    asyncio.run(automate(args))

if __name__ == "__main__":
    main()
