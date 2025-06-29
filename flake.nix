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

        # Create a script that runs the agent with a specific prompt file
        agentScript = promptFile: pkgs.writeScriptBin "agent" ''
          #!${pkgs.bash}/bin/bash
          # Python packages available in the agent's environment:
          # numpy, matplotlib, scikit-learn, ipykernel, torch, tqdm, gymnasium, torchvision, tensorboard, torch-tb-profiler, opencv-python, nbconvert, anthropic, seaborn
          exec ${pkgs.python3.withPackages (ps: with ps; [
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
          ])}/bin/python3 ${./agent.py} --prompt-file ${promptFile} "$@"
        '';

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
        ]);

        agentEntrypoint = pkgs.writeScript "entrypoint.sh" ''
          #!${pkgs.bash}/bin/bash
          exec ${pythonEnv}/bin/python3  ${./agent.py} --prompt-file ${./prompt.md} "$@"
        '';

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
          contents = [ pythonEnv pkgs.bash ];
          config = {
            Entrypoint = [ "${agentEntrypoint}" ];
            WorkingDir = "/app";
            Env = [ "PYTHONUNBUFFERED=1" ];
          };
        };
      }
    );
}
