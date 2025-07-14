{
  description = "A basic rust cli";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  # inputs.unstable.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.flake-utils.url = "github:numtide/flake-utils";

  outputs = { self, nixpkgs, flake-utils, ... }@inputs:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        devshell = pkgs.callPackage ./shell.nix { inherit pkgs; };

        # Create a proper derivation that includes all files
        agentPackage = pkgs.stdenv.mkDerivation {
          name = "bash-agent";
          src = ./.;
          buildInputs = [ pythonEnv ];
          installPhase = ''
            mkdir -p $out/bin $out/share/bash-agent
            cp -r . $out/share/bash-agent/
            cat > $out/bin/agent << EOF
            #!${pkgs.bash}/bin/bash
            cd $out/share/bash-agent
            exec ${pythonEnv}/bin/python3 $out/share/bash-agent/agent.py "\$@"
            EOF
            chmod +x $out/bin/agent
          '';
        };

        # Create a proper derivation for bash-agent (legacy)
        bashAgentPackage = pkgs.stdenv.mkDerivation {
          name = "bash-agent-legacy";
          src = ./.;
          buildInputs = [ pythonEnv ];
          installPhase = ''
            mkdir -p $out/bin $out/share/bash-agent
            cp -r . $out/share/bash-agent/
            cat > $out/bin/bash-agent << EOF
            #!${pkgs.bash}/bin/bash
            cd $out/share/bash-agent
            exec ${pythonEnv}/bin/python3 $out/share/bash-agent/bash-agent.py "\$@"
            EOF
            chmod +x $out/bin/bash-agent
          '';
        };

        # Create a proper derivation for webagent (new)
        webAgentPackage = pkgs.stdenv.mkDerivation {
          name = "web-agent";
          src = ./.;
          buildInputs = [ pythonEnv ];
          installPhase = ''
            mkdir -p $out/bin $out/share/bash-agent
            cp -r . $out/share/bash-agent/
            cat > $out/bin/webagent << EOF
            #!${pkgs.bash}/bin/bash
            cd $out/share/bash-agent
            exec ${pythonEnv}/bin/python3 $out/share/bash-agent/agent.py "\$@"
            EOF
            chmod +x $out/bin/webagent
          '';
        };

        agentScript = agentPackage;
        bashAgentScript = bashAgentPackage;
        webAgentScript = webAgentPackage;

        pythonEnv = pkgs.python3.withPackages (ps:
          with ps; [
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
            chromadb
            langchain
            langchain-openai
            langchain-chroma
            langchain-core
          ]);

        # Web agent entrypoint
        agentEntrypoint = pkgs.writeScript "entrypoint.sh" ''
          #!${pkgs.bash}/bin/bash
          cd ${agentPackage}/share/bash-agent
          exec ${pythonEnv}/bin/python3 ${agentPackage}/share/bash-agent/agent.py "$@"
        '';

        # Bash agent entrypoint (legacy)
        bashAgentEntrypoint = pkgs.writeScript "bash-entrypoint.sh" ''
          #!${pkgs.bash}/bin/bash
          cd ${bashAgentPackage}/share/bash-agent
          exec ${pythonEnv}/bin/python3 ${bashAgentPackage}/share/bash-agent/bash-agent.py "$@"
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
          kubectl
          kubernetes-helm
          curl
          wget
          which
          gnused
          # Add C++ standard library and GCC runtime
          stdenv.cc.cc.lib
          glibc
          sqlite
          nettools
          procps
          cacert

        ];

      in {
        devShells.default = devshell;

        # Packages
        packages.default = agentScript;
        packages.webAgent = webAgentScript;
        packages.bashAgent = bashAgentScript;

        # Apps for running with nix run
        apps.default = {
          type = "app";
          program = "${(bashAgentScript)}/bin/bash-agent";
        };

        apps.webagent = {
          type = "app";
          program = "${(webAgentScript)}/bin/webagent";
        };

        apps.bashagent = {
          type = "app";
          program = "${(bashAgentScript)}/bin/bash-agent";
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
            User = "1000:1000";
            Env = [
              "PYTHONUNBUFFERED=1"
              "LD_LIBRARY_PATH=${pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.glibc ]}"
              "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
              "GIT_SSL_CAINFO=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
              "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
              "CURL_CA_BUNDLE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            ];
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
            User = "1000:1000";
            Env = [
              "PYTHONUNBUFFERED=1"
              "LD_LIBRARY_PATH=${pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.glibc ]}"
              "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
              "GIT_SSL_CAINFO=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
              "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
              "CURL_CA_BUNDLE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            ];
          };
        };
      });
}
