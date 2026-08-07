#!/bin/sh
# BenchFlow launcher for Prime Agent (ACP mode).
#
# Deployed to /opt/benchflow/bin/prime-agent-acp by the manifest install_cmd
# (base64-embedded; regenerate with: base64 < launcher.sh | tr -d '\n').
#
# What it does:
#   1. Builds a models.json declaring a single custom provider ("benchflow")
#      that points at the BenchFlow-provided OpenAI-compatible endpoint (the
#      LiteLLM gateway by default). Prime Agent resolves the API key by env
#      var NAME, so no secret is written to disk.
#   2. When the model id looks like a DeepSeek model, mirrors Prime Agent's
#      built-in DeepSeek catalog entry (reasoning + thinkingLevelMap) plus the
#      FULL effective compat a native run computes. Prime Agent auto-detects
#      compat from the base URL (openai-completions.ts resolveCompat): with
#      baseUrl=api.deepseek.com it classifies DeepSeek "non-standard" and sends
#      the system prompt as role "system" with no "store" field; behind a proxy
#      base URL that detection flips and it sends role "developer" (+store),
#      which DeepSeek's own API rejects with a 400 (verified live) and which
#      only works through gateways that quietly translate the role. Declaring
#      supportsDeveloperRole=false/supportsStore=false/maxTokensField keeps the
#      agent's wire behavior byte-compatible with a native DeepSeek run.
#   3. Execs prime-agent in ACP mode with the model fixed at launch (Prime
#      Agent has no ACP set_model; model selection is env-owned).
#
# The kernel venv and agent home are /opt-anchored so the agent works the same
# whether the rollout runs as root or a dropped-privilege sandbox user.
set -eu
PA_ROOT=/opt/benchflow/prime-agent
PA_HOME=$PA_ROOT/home
MODEL=${PRIME_AGENT_MODEL:-${BENCHFLOW_PROVIDER_MODEL:-}}
BASE=${PRIME_AGENT_PROVIDER_BASE_URL:-${BENCHFLOW_PROVIDER_BASE_URL:-}}
if [ -z "$MODEL" ] || [ -z "$BASE" ]; then
  echo "prime-agent-acp: need a model (PRIME_AGENT_MODEL or BENCHFLOW_PROVIDER_MODEL) and a base URL (PRIME_AGENT_PROVIDER_BASE_URL or BENCHFLOW_PROVIDER_BASE_URL)" >&2
  exit 64
fi
BASE=${BASE%/}
case "$BASE" in */v1) ;; *) BASE=$BASE/v1 ;; esac
if [ -n "${PRIME_AGENT_PROVIDER_API_KEY:-}" ]; then
  KEYVAR=PRIME_AGENT_PROVIDER_API_KEY
else
  KEYVAR=BENCHFLOW_PROVIDER_API_KEY
fi
mkdir -p "$PA_HOME"
case "$MODEL" in
  *deepseek*)
    MODEL_JSON=$(printf '{"id":"%s","name":"%s","reasoning":true,"contextWindow":1000000,"maxTokens":384000,"thinkingLevelMap":{"minimal":null,"low":null,"medium":null,"high":"high","xhigh":"max"},"compat":{"supportsStore":false,"supportsDeveloperRole":false,"maxTokensField":"max_completion_tokens","requiresReasoningContentOnAssistantMessages":true,"thinkingFormat":"deepseek"}}' "$MODEL" "$MODEL")
    ;;
  *)
    MODEL_JSON=$(printf '{"id":"%s","name":"%s"}' "$MODEL" "$MODEL")
    ;;
esac
printf '{"providers":{"benchflow":{"baseUrl":"%s","api":"openai-completions","apiKey":"%s","models":[%s]}}}\n' \
  "$BASE" "$KEYVAR" "$MODEL_JSON" > "$PA_HOME/models.json"
export PRIME_AGENT_CODING_AGENT_DIR="$PA_HOME"
export PRIME_AGENT_KERNEL_PYTHON="$PA_ROOT/kernel-venv/bin/python"
export IPYTHONDIR="$PA_HOME/ipython"
export PI_SKIP_VERSION_CHECK=1
exec env -u NODE_OPTIONS -u HTTP_PROXY -u HTTPS_PROXY -u NO_PROXY \
  -u http_proxy -u https_proxy -u no_proxy -u NODE_TLS_REJECT_UNAUTHORIZED \
  /opt/benchflow/bin/prime-agent --mode acp --no-session --provider benchflow --model "$MODEL"
