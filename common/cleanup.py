import os
import subprocess, signal

def cleanup_rsu():
    p = subprocess.Popen(['ps', '-ef'], stdout=subprocess.PIPE)
    out, err = p.communicate()

    for line in out.splitlines():
        if 'xc_rsu' in line:
           print line
           #pid = int(line.split(None, 1)[0])
           #pidstr = line.split(None, 1)[1]
           pidstr = line.split()[1]
           print pidstr
           pid = int(pidstr)
           os.kill(pid, signal.SIGKILL)
