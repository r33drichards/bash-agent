{ pkgs ? import <nixpkgs> { }, inputs ? { } }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    # Python environment with all required packages
    (python3.withPackages (ps: with ps; [
      anthropic
      tenacity
      matplotlib
      ipython
      numpy
      pandas
      seaborn
      scikit-learn
      ipykernel
      torch
      tqdm
      gymnasium
      torchvision
      tensorboard
      torch-tb-profiler
      opencv-python
      nbconvert
      patch
      kubernetes
      flask
      flask-socketio
      psutil
    ]))
    
    # System utilities
    bash
    coreutils
    findutils
    git
    nix
    gnugrep
    gnutar
    openssh
    nodejs
    gawk
    unzip
    kubectl
    kubernetes-helm
    curl
    wget
    which
    gnused
    sqlite
    nettools
    ps
    inputs.nix-mcp-servers.packages.${pkgs.system}.mcp-server-filesystem
    inputs.nix-mcp-servers.packages.${pkgs.system}.mcp-server-playwright
  ];
  
  shellHook = ''
    echo "Bash Agent development environment loaded!"
    echo "Available commands:"
    echo "  python agent.py --help       # Start web agent"
    echo "  python bash-agent.py --help  # Start CLI agent"
    echo ""
    echo "Session persistence features:"
    echo "  - Cmd+K creates new sessions"
    echo "  - Sessions persist across server restarts"
    echo "  - Background tasks are restored"
  '';
}