{ pkgs ? import <nixpkgs> { }, inputs ? { } }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    nodejs
  ];
  shellHook = ''
    alias claude='npx @anthropic-ai/claude-code'
  '';
}