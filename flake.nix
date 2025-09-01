{
  description = "A basic rust cli";

  inputs = {
    system-manager = {
      url = "github:numtide/system-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    # unstable.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    nix-mcp-servers.url = "github:cameronfyfe/nix-mcp-servers";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      system-manager,
      ...
    }@inputs:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        lib = pkgs.lib;

        devshell = pkgs.callPackage ./shell.nix {
          inherit pkgs;
          inputs = inputs;
        };

        # Create a proper derivation for webagent (new)
        webAgentPackage = pkgs.stdenv.mkDerivation {
          name = "agent";
          src = ./.;
          checkPhase = ''
            runHook preCheck
            echo "Running tests..."
            cd $src
            ${testPythonEnv}/bin/python -m pytest -v --tb=short -W ignore::pytest.PytestCacheWarning .
            runHook postCheck
          '';
          doCheck = false;
          buildPhase = ''
            echo "Build phase completed"
          '';
          installPhase = ''
            mkdir -p $out/bin
            cp -r $src/* $out/bin/
            chmod +x $out/bin/main.py
          '';
          meta = {
            mainProgram = "main.py";
          };
        };

        webAgentScript = webAgentPackage;

        pythonPackages =
          ps: with ps; [
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
            fpdf
            mcp
            ps.playwright
          ];

        testPythonPackages =
          ps:
          with ps;
          [
            pytest
          ]
          ++ pythonPackages ps;

        pythonEnv = pkgs.python3.withPackages pythonPackages;

        testPythonEnv = pkgs.python3.withPackages testPythonPackages;

        # Web agent executable using writeShellApplication
        webAgentExecutable = pkgs.writeShellApplication {
          name = "webagent";
          runtimeInputs = [
            pythonEnv
            inputs.nix-mcp-servers.packages.${system}.mcp-server-filesystem
            inputs.nix-mcp-servers.packages.${system}.mcp-server-sequentialthinking
            inputs.nix-mcp-servers.packages.${system}.mcp-server-memory
            inputs.nix-mcp-servers.packages.${system}.mcp-server-playwright
          ];
          text = ''
            ${pythonEnv}/bin/python3 ${lib.getExe webAgentPackage} "$@"
          '';
        };

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
          poetry
        ];

      in
      {
        devShells.default = devshell;

        # Packages
        packages.default = webAgentExecutable;
        packages.webAgent = webAgentExecutable;

        apps.webagent = {
          type = "app";
          program = lib.getExe webAgentExecutable;
        };

        # New web agent Docker image (using agent.py)
        packages.webAgentDocker = pkgs.dockerTools.streamLayeredImage {
          name = "webagent";
          tag = "latest";
          maxLayers = 120;
          contents = baseContents;
          config = {
            Entrypoint = [ "${lib.getExe webAgentExecutable}" ];
            WorkingDir = "/app";
            User = "1000:1000";
            Env = [
              "PYTHONUNBUFFERED=1"
              "LD_LIBRARY_PATH=${
                pkgs.lib.makeLibraryPath [
                  pkgs.stdenv.cc.cc.lib
                  pkgs.glibc
                ]
              }"
              "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
              "GIT_SSL_CAINFO=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
              "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
              "CURL_CA_BUNDLE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            ];
          };
        };

        systemConfigs.default = system-manager.lib.makeSystemConfig {
          modules = [
            (
              {
                config,
                lib,
                pkgs,
                ...
              }:

              {
                config = {
                  nixpkgs.hostPlatform = "x86_64-linux";
                  environment = {
                    systemPackages = baseContents;
                  };

                  
                  systemd.services = {
                    web-agent = {
                      enable = true;
                      description = "Web Agent Service";
                      after = [ "network.target" ];
                      wantedBy = [ "multi-user.target" ];

                      serviceConfig = {
                        Type = "simple";
                        User = "robertwendt";
                        Group = "users";
                        WorkingDirectory = "/home/robertwendt";
                        Restart = "on-failure";
                        RestartSec = "5s";
                      };
                      script = ''
                        exec ${lib.getExe webAgentExecutable} --working-dir /home/robertwendt/ --metadata-dir /home/robertwendt/meta --title "$(${pkgs.hostname}/bin/hostname)" "$@"
                      '';
                    };
                  };
                };
              }
            )
          ];
        };

      }
    );
}
