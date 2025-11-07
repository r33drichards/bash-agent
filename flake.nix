{
  description = "MCP Server for Bash, SQLite, and IPython tools";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        lib = pkgs.lib;

        # Python packages needed for the MCP server
        pythonPackages =
          ps: with ps; [
            mcp
            ipython
            matplotlib
            numpy
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

        # MCP Server package
        mcpServerPackage = pkgs.stdenv.mkDerivation {
          name = "bash-tools-mcp-server";
          version = "0.1.0";
          src = ./.;

          checkPhase = ''
            runHook preCheck
            echo "Running tests..."
            cd $src
            ${testPythonEnv}/bin/python -m pytest -v --tb=short -W ignore::pytest.PytestCacheWarning . || true
            runHook postCheck
          '';
          doCheck = false;

          buildPhase = ''
            echo "Build phase completed"
          '';

          installPhase = ''
            mkdir -p $out/bin
            mkdir -p $out/lib/python
            cp -r $src/tools $out/lib/python/
            cp $src/mcp_server.py $out/lib/python/

            # Create wrapper script
            cat > $out/bin/bash-tools-mcp-server <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$out/lib/python:\$PYTHONPATH"
exec ${pythonEnv}/bin/python $out/lib/python/mcp_server.py "\$@"
EOF
            chmod +x $out/bin/bash-tools-mcp-server
          '';

          meta = {
            description = "MCP server providing bash, SQLite, and IPython execution tools";
            mainProgram = "bash-tools-mcp-server";
          };
        };

        # MCP Server executable
        mcpServerExecutable = pkgs.writeShellApplication {
          name = "bash-tools-mcp-server";
          runtimeInputs = [ pythonEnv ];
          text = ''
            exec ${pythonEnv}/bin/python ${mcpServerPackage}/lib/python/mcp_server.py "$@"
          '';
        };

      in
      {
        # Development shell
        devShells.default = pkgs.mkShell {
          buildInputs = [
            pythonEnv
            pkgs.sqlite
          ];

          shellHook = ''
            echo "MCP Server development environment"
            echo "Run 'bash-tools-mcp-server' to start the server"
          '';
        };

        # Packages
        packages = {
          default = mcpServerExecutable;
          mcp-server = mcpServerExecutable;
        };

        apps = {
          default = {
            type = "app";
            program = lib.getExe mcpServerExecutable;
          };
          mcp-server = {
            type = "app";
            program = lib.getExe mcpServerExecutable;
          };
        };
      }
    );
}
