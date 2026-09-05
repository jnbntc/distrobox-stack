#!/usr/bin/env bash
SESSION="htb"

# Evita anidar tmux si ya estás adentro
if [ -n "$TMUX" ]; then
    echo "[!] Ya estás dentro de una sesión de Tmux."
    exit 1
fi

tmux has-session -t $SESSION 2>/dev/null
if [ $? != 0 ]; then
  tmux new-session -d -s $SESSION -n 'VPN'
  
  # Ventana 1: VPN (Requiere sudo por el unshare_net=1) y Bmon
  tmux send-keys -t $SESSION:0.0 'sudo openvpn --config /htb/vpn/lab.ovpn' C-m
  tmux split-window -h -t $SESSION:0
  tmux send-keys -t $SESSION:0.1 'bmon -p tun0' C-m

  # Ventana 2: Enum (Guarda logs por defecto en /htb/logs usando tmux-logging)
  tmux new-window -t $SESSION:1 -n 'Enum'
  tmux send-keys -t $SESSION:1 'cd /htb/scans' C-m
  
  # Ventana 3: Exploit
  tmux new-window -t $SESSION:2 -n 'Exploit'
  tmux send-keys -t $SESSION:2 'cd /htb/exploits' C-m

  # Ventana 4: Catch (Listener Pwncat)
  tmux new-window -t $SESSION:3 -n 'Catch'
  tmux send-keys -t $SESSION:3 'pwncat-cs -lb 4444' C-m

  # Ventana 5: Servidor de Binarios (Pivoting/PrivEsc)
  tmux new-window -t $SESSION:4 -n 'Loot-Server'
  tmux send-keys -t $SESSION:4 'cd /opt/static_tools && python3 -m http.server 80' C-m
fi

tmux attach -t $SESSION:0
