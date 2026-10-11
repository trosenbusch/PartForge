"""FOLLOW-UP 05b (UNVERIFIED): measure DelphiScript launch latency.

Precondition: ALTIUM_MCP_CHECKOUT points to the local altium-mcp checkout; Sandbox.pas holds the ping body from 05_latency_ping_body.txt
(run it once via mcp__altium__run_altium_script). This harness does NOT modify Sandbox.pas;
it only re-launches the sandbox script project the same way altium-mcp does.
"""
import os
import subprocess
import sys
import time

X2 = r"C:\Program Files\Altium\AD22\X2.EXE"
PRJ = os.path.join(os.environ["ALTIUM_MCP_CHECKOUT"], "server", "SandboxScript", "Sandbox.PrjScr")
PING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ping.txt")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5

samples = []
for i in range(N):
    if os.path.exists(PING):
        os.remove(PING)
    t0 = time.perf_counter()
    subprocess.Popen(f'"{X2}" -RScriptingSystem:RunScript(ProjectName="{PRJ}"^|ProcName="Sandbox>Run")',
                     shell=True)
    while not os.path.exists(PING):
        if time.perf_counter() - t0 > 30:
            print("timeout - executor wedged? stop and check Altium")
            sys.exit(1)
        time.sleep(0.01)
    dt = (time.perf_counter() - t0) * 1000
    samples.append(dt)
    print(f"run {i}: {dt:.0f} ms")
    time.sleep(1.0)
print(f"min {min(samples):.0f} ms, median {sorted(samples)[len(samples)//2]:.0f} ms, max {max(samples):.0f} ms")
