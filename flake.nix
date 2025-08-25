{
  description = "A basic rust cli";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  # inputs.unstable.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.nix-mcp-servers.url = "github:cameronfyfe/nix-mcp-servers";

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
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

        playwrightMcp = pkgs.callPackage ./mcp-server-playwright {
          inherit pkgs;
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
            playwrightMcp
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
          google-chrome
        ];

        # Create Chrome at expected Playwright location and then start agentexecutable
        chromeLayout = pkgs.runCommand "chrome-layout" {} ''
          mkdir -p $out/opt/google/chrome
          cp ${lib.getExe pkgs.google-chrome} $out/opt/google/chrome/chrome 
          chmod +x $out/opt/google/chrome/chrome
        '';

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
          contents = baseContents ++ [ chromeLayout ];
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
      }
    );
}
