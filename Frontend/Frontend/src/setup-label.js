export function parseSetupLabel(value) {
  if (typeof value !== "string" || value.length > 2048) {
    throw new Error("Use a caughtIn4K Pi setup label.");
  }
  let label;
  try {
    label = JSON.parse(value);
  } catch {
    throw new Error("Paste the setup text supplied with your new Pi, or copied from its setup email.");
  }
  if (!label || typeof label !== "object" || Array.isArray(label)
    || Object.keys(label).length !== 3 || label.version !== 1
    || typeof label.gateway_id !== "string"
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(label.gateway_id)
    || typeof label.pairing_code !== "string" || !label.pairing_code.trim()
    || label.pairing_code.length > 256) {
    throw new Error("Use the caughtIn4K setup label, not the Pi machine credential.");
  }
  return { version: 1, gateway_id: label.gateway_id, pairing_code: label.pairing_code.trim() };
}
