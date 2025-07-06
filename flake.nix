{
  description = "A basic rust cli";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  # inputs.unstable.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.flake-utils.url = "github:numtide/flake-utils";


  outputs = { self, nixpkgs, flake-utils, ... }@inputs:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };

        devshell = pkgs.callPackage ./shell.nix { inherit pkgs; };

        # Create a proper derivation that includes all files
        agentPackage = promptFile: pkgs.stdenv.mkDerivation {
          name = "bash-agent";
          src = ./.;
          buildInputs = [ pythonEnv ];
          installPhase = ''
            mkdir -p $out/bin $out/share/bash-agent
            cp -r . $out/share/bash-agent/
            cat > $out/bin/agent << EOF
            #!${pkgs.bash}/bin/bash
            cd $out/share/bash-agent
            exec ${pythonEnv}/bin/python3 $out/share/bash-agent/agent.py --prompt-file $out/share/bash-agent/prompt.md "\$@"
            EOF
            chmod +x $out/bin/agent
          '';
        };

        # Create a proper derivation for bash-agent (legacy)
        bashAgentPackage = promptFile: pkgs.stdenv.mkDerivation {
          name = "bash-agent-legacy";
          src = ./.;
          buildInputs = [ pythonEnv ];
          installPhase = ''
            mkdir -p $out/bin $out/share/bash-agent
            cp -r . $out/share/bash-agent/
            cat > $out/bin/bash-agent << EOF
            #!${pkgs.bash}/bin/bash
            cd $out/share/bash-agent
            exec ${pythonEnv}/bin/python3 $out/share/bash-agent/bash-agent.py --prompt-file $out/share/bash-agent/prompt.md "\$@"
            EOF
            chmod +x $out/bin/bash-agent
          '';
        };

        # Create a proper derivation for webagent (new)
        webAgentPackage = promptFile: pkgs.stdenv.mkDerivation {
          name = "web-agent";
          src = ./.;
          buildInputs = [ pythonEnv ];
          installPhase = ''
            mkdir -p $out/bin $out/share/bash-agent
            cp -r . $out/share/bash-agent/
            cat > $out/bin/webagent << EOF
            #!${pkgs.bash}/bin/bash
            cd $out/share/bash-agent
            exec ${pythonEnv}/bin/python3 $out/share/bash-agent/agent.py --prompt-file $out/share/bash-agent/prompt.md "\$@"
            EOF
            chmod +x $out/bin/webagent
          '';
        };

        # Create a script that runs the agent with a specific prompt file
        agentScript = promptFile: agentPackage promptFile;
        bashAgentScript = promptFile: bashAgentPackage promptFile;
        webAgentScript = promptFile: webAgentPackage promptFile;

        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
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
        ]);

        # Web agent entrypoint
        agentEntrypoint = pkgs.writeScript "entrypoint.sh" ''
          #!${pkgs.bash}/bin/bash
          cd ${agentPackage ./prompt.md}/share/bash-agent
          exec ${pythonEnv}/bin/python3 ${agentPackage ./prompt.md}/share/bash-agent/agent.py --prompt-file ${agentPackage ./prompt.md}/share/bash-agent/prompt.md "$@"
        '';

        # Bash agent entrypoint (legacy)
        bashAgentEntrypoint = pkgs.writeScript "bash-entrypoint.sh" ''
          #!${pkgs.bash}/bin/bash
          cd ${bashAgentPackage ./prompt.md}/share/bash-agent
          exec ${pythonEnv}/bin/python3 ${bashAgentPackage ./prompt.md}/share/bash-agent/bash-agent.py --prompt-file ${bashAgentPackage ./prompt.md}/share/bash-agent/prompt.md "$@"
        '';

        baseContents = with pkgs; [ 
            pythonEnv
            bash 
            coreutils 
            findutils 
            git 
            nix 
            gnugrep 
            gnutar
            openssh
            pkgs.nodejs
            gawk
            unzip
          ];

      in
      {
        devShells.default = devshell;
        
        # Packages
        packages.default = agentScript ./prompt.md;
        packages.webAgent = webAgentScript ./prompt.md;
        packages.bashAgent = bashAgentScript ./prompt.md;
        
        # Apps for running with nix run
        apps.default = {
          type = "app";
          program = "${(bashAgentScript ./prompt.md)}/bin/bash-agent";
        };
        
        apps.webagent = {
          type = "app";
          program = "${(webAgentScript ./prompt.md)}/bin/webagent";
        };

        apps.bashagent = {
          type = "app";
          program = "${(bashAgentScript ./prompt.md)}/bin/bash-agent";
        };
        
        # Docker images
        packages.bashAgentDocker = pkgs.dockerTools.streamLayeredImage {
          name = "bash-agent";
          tag = "latest";
          maxLayers = 120;
          contents = baseContents;
          config = {
            Entrypoint = [ "${bashAgentEntrypoint}" ];
            WorkingDir = "/app";
            Env = [ "PYTHONUNBUFFERED=1" ];
          };
        };

        # New web agent Docker image (using agent.py)
        packages.webAgentDocker = pkgs.dockerTools.streamLayeredImage {
          name = "webagent";
          tag = "latest";
          maxLayers = 120;
          contents = baseContents;
          config = {
            Entrypoint = [ "${agentEntrypoint}" ];
            WorkingDir = "/app";
            Env = [ "PYTHONUNBUFFERED=1" ];
          };
        };
      }
    );
}