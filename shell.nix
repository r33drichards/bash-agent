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
    # inputs.nix-mcp-servers.packages.${pkgs.system}.mcp-server-filesystem
    # inputs.nix-mcp-servers.packages.${pkgs.system}.mcp-server-playwright
  ];
  

}