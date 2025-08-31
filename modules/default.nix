{ config, lib, pkgs, ... }:

{
config = {
  nixpkgs.hostPlatform = "x86_64-linux";



  environment = {
    systemPackages = [
      pkgs.ripgrep
      pkgs.fd
      pkgs.python3
      pkgs.nodejs
    ];
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
        
        # Security hardening
        PrivateTmp = true;
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = "read-only";
        ReadWritePaths = [
          "/home/robertwendt/"
          "/home/robertwendt/meta"
        ];
      };
      
      environment = {
        ANTHROPIC_API_KEY = "\${ANTHROPIC_API_KEY}";
      };
      
      script = ''
        exec ${pkgs.python3}/bin/python /home/robertwendt/bash-agent/main.py \
          --working-dir /home/robertwendt/ \
          --metadata-dir /home/robertwendt/meta \
          --port 5556 \
          --host 0.0.0.0 \
          --title "$(${pkgs.hostname}/bin/hostname)"
      '';
    };
  };
};
}