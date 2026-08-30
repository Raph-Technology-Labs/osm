// Config-driven names (actuators, error registers, camera ids) come from
// machine_config.yaml as raw snake_case/lowercase identifiers -- this only
// affects display, never the value sent back to the API.
export const toTitleCase = (raw) =>
  raw
    .replace(/[_-]+/g, " ")
    .trim()
    .split(" ")
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(" ");
