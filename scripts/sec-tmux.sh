#!/usr/bin/env bash
SESSION="sec"

if [ -n "$TMUX" ]; then
    echo "[!] Ya estás dentro de una sesión de Tmux."
    exit 1
fi

tmux has-session -t $SESSION 2>/dev/null
if [ $? != 0 ]; then
  tmux new-session -d -s $SESSION -n 'VPN'
  
  tmux send-keys -t $SESSION:0.0 'sudo openvpn --config /sec/vpn/lab.ovpn' C-m
  tmux split-window -h -t $SESSION:0
  tmux send-keys -t $SESSION:0.1 'bmon -p tun0' C-m

  tmux new-window -t $SESSION:1 -n 'Enum'
  tmux send-keys -t $SESSION:1 'cd /sec/scans' C-m
  
  tmux new-window -t $SESSION:2 -n 'Exploit'
  tmux send-keys -t $SESSION:2 'cd /sec/exploits' C-m

  tmux new-window -t $SESSION:3 -n 'Catch'
  tmux send-keys -t $SESSION:3 'pwncat-cs -lb 4444' C-m

  tmux new-window -t $SESSION:4 -n 'Loot-Server'
  tmux send-keys -t $SESSION:4 'cd /opt/static_tools && python3 -m http.server 80' C-m
fi

tmux attach -t $SESSION:0
