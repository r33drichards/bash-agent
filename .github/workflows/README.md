# GitHub Actions Workflows

This directory contains CI/CD workflows for the bash-agent project.

## Workflows

### `docker.yml` - CI/CD Pipeline
**Triggers:** Push to `main`, PRs to `main`

Builds and publishes Docker images:
- Builds webAgent Docker image using Nix
- Streams to Docker Hub using skopeo
- Tags with commit SHA and `latest`

**Requirements:**
- `DOCKER_PASSWORD` secret must be set

### `test-mcp-server.yml` - MCP Server Tests
**Triggers:** Push to `main` or `claude/**` branches, PRs to `main`

**Paths monitored:**
- `mcp-server-git-rag/**`
- `github_rag.py`
- `test-git-rag-integration.sh`
- `flake.nix`, `flake.lock`

**Jobs:**

#### 1. Structure Validation
- Runs without Nix dependencies
- Validates Python syntax
- Checks configuration files
- Verifies documentation completeness
- **Always runs** on every push/PR

#### 2. Nix Tests
- Sets up Nix environment
- Builds MCP server package
- Runs dependency checks
- Verifies all required imports work
- Tests server instantiation
- **Always runs** on every push/PR

#### 3. Integration Tests (Conditional)
- Runs full integration tests
- Tests actual repository indexing and querying
- Requires OpenAI API for embeddings
- **Only runs if** `OPENAI_API_KEY` secret is set
- **Optional** - workflow succeeds even if this job is skipped

#### 4. Build Verification
- Builds all packages (webAgent, mcp-server-git-rag)
- Verifies package structure
- Ensures builds complete successfully
- **Always runs** on every push/PR

**Caching:**
- Nix store is cached per job
- Cache key includes `flake.nix` and `flake.lock` hashes
- Reduces build times significantly

## Setting Up Secrets

### Required Secrets
- None (basic tests run without secrets)

### Optional Secrets
- `OPENAI_API_KEY` - Enables integration tests with actual API calls
- `DOCKER_PASSWORD` - Required for Docker publishing (docker.yml)

### How to Add Secrets
1. Go to repository Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Add secret name and value
4. Secrets are encrypted and only exposed to workflows

## Workflow Status Badges

Add to README.md:

```markdown
![CI/CD Pipeline](https://github.com/r33drichards/bash-agent/workflows/CI%2FCD%20Pipeline/badge.svg)
![MCP Server Tests](https://github.com/r33drichards/bash-agent/workflows/MCP%20Server%20Tests/badge.svg)
```

## Local Testing

### Test Structure Validation Locally
```bash
cd mcp-server-git-rag
python3 test_structure.py
```

### Test with Nix Locally
```bash
nix develop
python3 mcp-server-git-rag/test_server.py
```

### Run Integration Tests Locally
```bash
export OPENAI_API_KEY="your-key"
nix develop
./test-git-rag-integration.sh
```

### Build Packages Locally
```bash
nix build .#webAgent
nix build .#mcp-server-git-rag
```

## Debugging Workflows

### View Logs
1. Go to Actions tab in GitHub
2. Click on workflow run
3. Click on specific job
4. Expand steps to view logs

### Common Issues

**Issue: Nix cache miss**
- Solution: Cache is rebuilt automatically on flake changes
- First run after flake.nix changes will be slower

**Issue: Integration tests skipped**
- Solution: This is expected if `OPENAI_API_KEY` secret is not set
- Workflow still succeeds

**Issue: Build fails**
- Check that flake.nix syntax is correct: `nix flake check`
- Ensure all dependencies are listed in flake.nix

## Workflow Development

### Testing Workflow Changes
1. Create a branch: `git checkout -b test-workflow`
2. Modify workflow files
3. Push to GitHub: `git push origin test-workflow`
4. Check Actions tab for results
5. Iterate as needed

### Best Practices
- Keep jobs focused and independent
- Cache Nix store to speed up builds
- Use conditional jobs for expensive operations
- Always validate YAML syntax before committing
- Document secret requirements

## Performance

### Typical Run Times
- Structure Validation: ~30 seconds
- Nix Tests: ~3-5 minutes (first run), ~1-2 minutes (cached)
- Integration Tests: ~5-10 minutes (if enabled)
- Build Verification: ~3-5 minutes (first run), ~1-2 minutes (cached)

### Parallelization
All jobs run in parallel except:
- Integration tests only run if secret is available
- Each job is independent and can complete separately

## Contributing

When adding new workflows:
1. Follow the existing naming convention
2. Add documentation to this README
3. Test locally before pushing
4. Use appropriate triggers and paths
5. Cache aggressively for Nix builds
6. Make secrets optional when possible
