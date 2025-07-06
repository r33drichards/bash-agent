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

        # Create a script that runs the agent with a specific prompt file
        agentScript = promptFile: agentPackage promptFile;

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

        agentEntrypoint = pkgs.writeScript "entrypoint.sh" ''
          #!${pkgs.bash}/bin/bash
          cd ${agentPackage ./prompt.md}/share/bash-agent
          exec ${pythonEnv}/bin/python3 ${agentPackage ./prompt.md}/share/bash-agent/agent.py --prompt-file ${agentPackage ./prompt.md}/share/bash-agent/prompt.md "$@"
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
          ];

      in
      {
        devShells.default = devshell;
        packages.default = agentScript ./prompt.md;
        apps.default = {
          type = "app";
          program = "${(agentScript ./prompt.md)}/bin/agent";
        };
        
        # Add a streaming layered Docker image output
        packages.streamLayered = pkgs.dockerTools.streamLayeredImage {
          name = "bash-agent";
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
