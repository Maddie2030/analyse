#!/usr/bin/env bash
set -euo pipefail
provider="${MREADER_CLOUD_PROVIDER:-existing}"
mode="${MREADER_REGISTRY_MODE:-external}"
registry="${MREADER_REGISTRY%%/*}"
out="${DOCKER_CONFIG:-/docker-config}"
mkdir -p "$out"
write_auth() {
  local user="$1" pass="$2" encoded
  encoded="$(printf '%s:%s' "$user" "$pass" | base64 | tr -d '\n')"
  printf '{"auths":{"%s":{"auth":"%s"}}}\n' "$registry" "$encoded" > "$out/config.json"
  chmod 0600 "$out/config.json"
}
if [[ "$mode" == external ]]; then
  : "${REGISTRY_USERNAME:?REGISTRY_USERNAME required}" "${REGISTRY_PASSWORD:?REGISTRY_PASSWORD required}"
  write_auth "$REGISTRY_USERNAME" "$REGISTRY_PASSWORD"
  exit 0
fi
case "$provider" in
  aws)
    : "${AWS_REGION:?}"
    write_auth AWS "$(aws ecr get-login-password --region "$AWS_REGION")"
    ;;
  azure)
    : "${AZURE_CLIENT_ID:?}" "${AZURE_TENANT_ID:?}" "${AZURE_ACR_NAME:?}"
    token_file="${AZURE_FEDERATED_TOKEN_FILE:-/var/run/secrets/azure/tokens/azure-identity-token}"
    az login --service-principal --username "$AZURE_CLIENT_ID" --tenant "$AZURE_TENANT_ID" --federated-token "$(cat "$token_file")" --allow-no-subscriptions >/dev/null
    token="$(az acr login --name "$AZURE_ACR_NAME" --expose-token --output tsv --query accessToken)"
    write_auth 00000000-0000-0000-0000-000000000000 "$token"
    ;;
  gcp)
    write_auth oauth2accesstoken "$(gcloud auth print-access-token)"
    ;;
  *) echo "cloud registry mode unsupported for provider: $provider" >&2; exit 2;;
esac
