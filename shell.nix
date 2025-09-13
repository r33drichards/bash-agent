{ pkgs ? import <nixpkgs> { }, inputs ? { }, pythonEnv, lib}:


pkgs.mkShell {
  buildInputs = with pkgs; [
    nodejs
    python3
    uv
    nixpkgs-fmt 
    nixfmt
    git 
    pythonEnv
    inputs.nix-mcp-servers.packages.${system}.mcp-server-filesystem
    inputs.nix-mcp-servers.packages.${system}.mcp-server-sequentialthinking
    inputs.nix-mcp-servers.packages.${system}.mcp-server-memory
    inputs.nix-mcp-servers.packages.${system}.mcp-server-playwright

  ];
  shellHook = ''
    alias claude='npx @anthropic-ai/claude-code'
    export LD_LIBRARY_PATH=${lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.glibc ]}
  '';
}