{ pkgs }:

pkgs.buildNpmPackage rec {
  pname = "mcp-server-playwright";
  version = "0.0.35";

  buildInputs = [ pkgs.nodejs ];

  src = pkgs.fetchFromGitHub {
    owner = "microsoft";
    repo = "playwright-mcp";
    rev = "v${version}";
    hash = "sha256-bF/F4dP2ri09AlQLItQwQxDAQybY2fXft4ccxSKijt8=";
  };



  npmDepsHash = "sha256-xSQCs6rJlUrdS8c580mo1/VjpcDxwHor0pdstB9VQEo=";
}