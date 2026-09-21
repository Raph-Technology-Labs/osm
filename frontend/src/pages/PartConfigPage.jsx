import { useCallback, useEffect, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import Autocomplete from "@mui/material/Autocomplete";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { useNavigate, useParams } from "react-router-dom";

import api from "../api/axios";
import { useAuth } from "../auth/AuthContext";

const inputSx = {
  "& .MuiOutlinedInput-root": { height: 44, borderRadius: 1.5 },
  "& .MuiOutlinedInput-input": { padding: "10px 12px", fontSize: "0.9rem" },
  "& .MuiInputLabel-root": { fontSize: "0.85rem" },
  "& .MuiFormLabel-asterisk": { color: "error.main", fontWeight: 700 },
};

const REGISTER_KEYS = [
  "pulse_count", "encoder_indexer_ppr", "encoder_count", "part_sensor",
  "heartbeat", "indexing_pulse", "heartbeat_per_slot", "indexing_pulse_per_slot",
  "reject_cmd", "stop_cmd", "speed_setpoint", "fault",
];

// Everything on this form is mandatory except these three. The backend's
// validate_form is the real gate (config_builder.OPTIONAL_PATHS) — this set
// only decides which labels get an asterisk, so keep the two in step.
const OPTIONAL_PATHS = new Set([
  "s1.measurement.model_path",
  "s1.camera.sim.image_path",
  "s2.camera.sim.image_path",
]);

/** Immutable set at a dotted path: setIn(form, "plc.sim.port", 5502). */
const setIn = (obj, path, value) => {
  const [head, ...rest] = path.split(".");
  if (!rest.length) return { ...obj, [head]: value };
  return { ...obj, [head]: setIn(obj[head] ?? {}, rest.join("."), value) };
};

const getIn = (obj, path) =>
  path.split(".").reduce((acc, k) => (acc == null ? acc : acc[k]), obj);

const Section = ({ title, subtitle, children, defaultExpanded = false }) => (
  <Accordion defaultExpanded={defaultExpanded} disableGutters>
    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
      <Box>
        <Typography sx={{ fontWeight: 700 }}>{title}</Typography>
        {subtitle && (
          <Typography variant="caption" color="text.secondary">
            {subtitle}
          </Typography>
        )}
      </Box>
    </AccordionSummary>
    <AccordionDetails>{children}</AccordionDetails>
  </Accordion>
);

const PartConfigPage = () => {
  const { partId: routePartId } = useParams();
  const navigate = useNavigate();
  const { isAdmin, isSuperAdmin } = useAuth();

  const [toast, setToast] = useState(null);
  const notify = (severity, message) => setToast({ severity, message });

  // ── Part picker ──────────────────────────────────────────────
  const [categories, setCategories] = useState([]);
  const [selectedCategoryId, setSelectedCategoryId] = useState("");
  const [parts, setParts] = useState([]);
  const [partsLoading, setPartsLoading] = useState(false);
  const [selectedPart, setSelectedPart] = useState(null);
  const [partId, setPartId] = useState(routePartId ? Number(routePartId) : null);

  // ── Config ───────────────────────────────────────────────────
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [meta, setMeta] = useState(null);
  const [form, setForm] = useState(null);

  // ── Restore ──────────────────────────────────────────────────
  const [restoring, setRestoring] = useState(false);
  const [confirmRestore, setConfirmRestore] = useState(false);

  const exists = meta?.exists;
  // Superadmin creates; admin and superadmin edit. The backend enforces
  // this by HTTP verb -- this only keeps the UI honest.
  const canSave = exists
    ? Boolean(isAdmin || isSuperAdmin)
    : Boolean(isSuperAdmin);

  // Categories once.
  useEffect(() => {
    api
      .get("/parts/categories")
      .then(({ data }) => setCategories(data))
      .catch(() => notify("error", "Failed to load categories."));
  }, []);

  // Parts for the chosen category.
  useEffect(() => {
    if (!selectedCategoryId) {
      setParts([]);
      return;
    }
    setPartsLoading(true);
    api
      .get("/parts", { params: { category_id: selectedCategoryId } })
      .then(({ data }) => setParts(data))
      .catch(() => {
        setParts([]);
        notify("error", "Failed to load parts for this category.");
      })
      .finally(() => setPartsLoading(false));
  }, [selectedCategoryId]);

  const loadConfig = useCallback(async (id) => {
    const { data } = await api.get(`/parts/${id}/config`);
    setMeta(data);
    setForm(data.form);
  }, []);

  // Config for whichever part is selected — by dropdown or by route.
  useEffect(() => {
    if (!partId) {
      setMeta(null);
      setForm(null);
      return;
    }
    setLoading(true);
    loadConfig(partId)
      .catch((e) => {
        setMeta(null);
        setForm(null);
        notify("error", e?.response?.data?.detail || "Failed to load the config.");
      })
      .finally(() => setLoading(false));
  }, [partId, loadConfig]);

  const field = useCallback(
    (path) => ({
      value: getIn(form, path) ?? "",
      onChange: (e) => setForm((f) => setIn(f, path, e.target.value)),
      // MUI appends the asterisk itself, so no label needs editing.
      required: !OPTIONAL_PATHS.has(path),
      sx: inputSx,
      size: "small",
      fullWidth: true,
    }),
    [form],
  );

  const numField = useCallback(
    (path) => ({
      ...field(path),
      inputProps: { inputMode: "decimal" },
      onChange: (e) => {
        const v = e.target.value;
        // Store the RAW string. Number("2.") is 2, which would delete the
        // decimal point the moment it is typed, making "2.56" unreachable.
        // config_builder._coerce converts it on save.
        if (v === "" || /^-?\d*\.?\d*$/.test(v)) {
          setForm((f) => setIn(f, path, v));
        }
      },
    }),
    [field],
  );

  const toggle = (path) => ({
    checked: Boolean(getIn(form, path)),
    onChange: (e) => setForm((f) => setIn(f, path, e.target.checked)),
  });

  const handleSave = async () => {
    setSaving(true);
    try {
      const body = { form };
      const { data } = exists
        ? await api.put(`/parts/${partId}/config`, body)
        : await api.post(`/parts/${partId}/config`, body);
      notify("success", `${data.message} — ${data.config_path}`);
      // Re-fetch so the YAML preview, version and previous-version banner
      // reflect what was actually saved.
      await loadConfig(partId);
    } catch (e) {
      notify("error", e?.response?.data?.detail || "Failed to save the config.");
    } finally {
      setSaving(false);
    }
  };

  const handleRestore = async () => {
    setConfirmRestore(false);
    setRestoring(true);
    try {
      const { data } = await api.post(`/parts/${partId}/config/restore-previous`);
      notify("success", data.message);
      await loadConfig(partId);
    } catch (e) {
      notify("error", e?.response?.data?.detail || "Failed to restore.");
    } finally {
      setRestoring(false);
    }
  };

  // The browser can't send an Authorization header on a plain link, so the
  // file is fetched as a blob and handed to a synthetic anchor.
  const handleDownload = async () => {
    try {
      const res = await api.get(`/parts/${partId}/config/download`, {
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = (meta.config_path || "machine_config.yaml").split("/").pop();
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (e) {
      notify("error", "Failed to download the config file.");
    }
  };

  const dimensionNames = Object.keys(meta?.dimensions || {});
  const defectNames = Object.keys(meta?.defects || {});

  return (
    <Box sx={{ height: "100%", overflowY: "auto", bgcolor: "background.default" }}>
      <Box sx={{ maxWidth: 1100, mx: "auto", px: { xs: 1.5, sm: 3 }, py: 3 }}>
        <Paper
          elevation={0}
          sx={{
            p: { xs: 2, sm: 3, md: 4 },
            borderRadius: 2,
            border: 1,
            borderColor: "divider",
          }}
        >
          <Typography variant="h5" sx={{ fontWeight: 700, mb: 0.5 }}>
            Machine Config
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Pick a part to load its config. A new part has none until a
            superadministrator creates one.
          </Typography>

          {/* ── Part picker ──────────────────────────────────── */}
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 3 }}>
            <TextField
              select
              label="Category"
              value={selectedCategoryId}
              onChange={(e) => {
                setSelectedCategoryId(e.target.value);
                setSelectedPart(null);
                setPartId(null);
              }}
              sx={{ ...inputSx, minWidth: 260 }}
              size="small"
            >
              {categories.map((c) => (
                <MenuItem key={c.category_id} value={c.category_id}>
                  {c.category_name}
                </MenuItem>
              ))}
            </TextField>

            <Autocomplete
              sx={{ flex: 1, minWidth: 260 }}
              options={parts}
              value={selectedPart}
              disabled={!selectedCategoryId || partsLoading}
              getOptionLabel={(o) => (o ? `${o.part_name} (${o.part_code})` : "")}
              isOptionEqualToValue={(a, b) => a.part_id === b.part_id}
              onChange={(e, v) => {
                setSelectedPart(v);
                setPartId(v ? v.part_id : null);
              }}
              renderInput={(p) => (
                <TextField
                  {...p}
                  label="Part"
                  size="small"
                  sx={inputSx}
                  placeholder={
                    selectedCategoryId
                      ? "Type a part name or code"
                      : "Choose a category first"
                  }
                />
              )}
            />
          </Stack>

          {loading && (
            <Typography color="text.secondary" sx={{ py: 4 }}>
              Loading config…
            </Typography>
          )}

          {!partId && !loading && (
            <Alert severity="info">
              Select a category and part above to view or edit its machine config.
            </Alert>
          )}

          {partId && !loading && form && (
            <>
              <Stack
                direction="row"
                spacing={1}
                alignItems="center"
                sx={{ mb: 2, flexWrap: "wrap", gap: 1 }}
              >
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                  {meta.part_name} · {meta.part_code}
                </Typography>
                <Chip
                  size="small"
                  color={exists ? "success" : "error"}
                  label={exists ? `Version ${meta.version}` : "Not configured"}
                />
                {meta.updated_at && (
                  <Typography variant="caption" color="text.secondary">
                    saved {new Date(meta.updated_at).toLocaleString()}
                  </Typography>
                )}
              </Stack>

              {/* An unconfigured part cannot run. The fields below are
                  blank on purpose — nothing is carried over from another
                  part, because these values decide machine behaviour. */}
              {!exists && (
                <Alert severity="error" sx={{ mb: 3 }}>
                  <b>{meta.part_code}</b> is not configured — it cannot run a
                  session until a machine config exists.
                  {canSave
                    ? " Fill in the fields below and press Create Config. Fields marked * are required; nothing is prefilled from another part."
                    : " Only a superadministrator can create one."}
                </Alert>
              )}

              {exists && !canSave && (
                <Alert severity="warning" sx={{ mb: 3 }}>
                  You do not have permission to edit this config.
                </Alert>
              )}

              {/* One save back, in case the current one was a mistake. */}
              {meta.previous && (
                <Alert
                  severity="info"
                  sx={{ mb: 3 }}
                  action={
                    <Button
                      color="inherit"
                      size="small"
                      disabled={!canSave || restoring || saving}
                      onClick={() => setConfirmRestore(true)}
                    >
                      {restoring ? "RESTORING…" : "RESTORE"}
                    </Button>
                  }
                >
                  Version {meta.previous.version} is still saved, from{" "}
                  {new Date(meta.previous.created_at).toLocaleString()}
                  {meta.previous.notes ? ` — ${meta.previous.notes}` : ""}.
                </Alert>
              )}

              {/* Derived from the part record — shown so it is clear what the
                  machine will use, and where those values are changed. */}
              <Alert severity="info" sx={{ mb: 3 }}>
                Tolerances and defect thresholds come from the part record, not
                this form.{" "}
                {dimensionNames.length > 0 ? (
                  <>
                    Measuring: <b>{dimensionNames.join(", ")}</b>.{" "}
                  </>
                ) : (
                  <>No dimensions on this part. </>
                )}
                {defectNames.length > 0 ? (
                  <>
                    Checking for: <b>{defectNames.join(", ")}</b>.
                  </>
                ) : (
                  <>No defects on this part.</>
                )}{" "}
                Edit them on the part itself.
              </Alert>

              <Box
                component="fieldset"
                disabled={!canSave || saving || restoring}
                sx={{ border: 0, p: 0, m: 0, minWidth: 0 }}
              >
                {/* ── Indexer ────────────────────────────────── */}
                <Section
                  title="Indexer"
                  subtitle="Ring geometry. n_slots is derived from these, not set directly."
                  defaultExpanded
                >
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField
                      label="Disc diameter (mm)"
                      {...numField("indexer.diameter_mm")}
                    />
                    <TextField label="Part size (mm)" {...numField("indexer.part_size_mm")} />
                    <TextField
                      label="Clearance tolerance (%)"
                      {...numField("indexer.tolerance_pct")}
                    />
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                    <TextField label="Encoder CPR" {...numField("indexer.encoder_cpr")} />
                    <TextField
                      label="Entry sensor mid-offset (pulses)"
                      {...numField("indexer.entry_sensor_mid_offset_pulses")}
                    />
                  </Stack>
                </Section>

                {/* ── PLC ────────────────────────────────────── */}
                <Section title="PLC" subtitle="Connection, timing and motor setpoint.">
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="PLC IP" {...field("plc.ip")} />
                    <TextField label="Port" {...numField("plc.port")} />
                    <TextField select label="Vendor" {...field("plc.vendor")}>
                      <MenuItem value="integra">integra</MenuItem>
                    </TextField>
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField
                      label="Real poll interval (ms)"
                      {...numField("plc.real_poll_interval_ms")}
                    />
                    <TextField
                      label="Speed setpoint (rpm)"
                      {...numField("plc.speed_setpoint_rpm")}
                    />
                    <TextField
                      label="Watchdog timeout (ms)"
                      {...numField("plc.watchdog_timeout_ms")}
                    />
                  </Stack>

                  <Typography variant="subtitle2" sx={{ fontWeight: 700, mt: 2, mb: 1 }}>
                    Simulation
                  </Typography>
                  <FormControlLabel
                    control={<Switch {...toggle("plc.sim.enabled")} />}
                    label="Run against the simulator instead of the real PLC"
                    sx={{ mb: 1 }}
                  />
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="Sim host" {...field("plc.sim.host")} />
                    <TextField label="Sim port" {...numField("plc.sim.port")} />
                    <TextField
                      label="Tick interval (ms)"
                      {...numField("plc.sim.tick_interval_ms")}
                    />
                    <TextField label="Blank slots" {...numField("plc.sim.blank")} />
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                    <TextField
                      label="Entry sensor delay (ms)"
                      {...numField("plc.sim.entry_sensor_response_delay_ms")}
                    />
                    <TextField
                      label="Reject actuator delay (ms)"
                      {...numField("plc.sim.reject_actuator_response_delay_ms")}
                    />
                  </Stack>
                </Section>

                {/* ── Registers ──────────────────────────────── */}
                <Section
                  title="Modbus Registers"
                  subtitle="Literal register numbers from the instrumentation sheet. Change only with their sign-off."
                >
                  <Box
                    sx={{
                      display: "grid",
                      gridTemplateColumns: {
                        xs: "1fr",
                        sm: "1fr 1fr",
                        md: "1fr 1fr 1fr",
                      },
                      gap: 2,
                    }}
                  >
                    {REGISTER_KEYS.map((key) => (
                      <TextField
                        key={key}
                        label={key}
                        {...numField(`plc.registers.${key}`)}
                      />
                    ))}
                  </Box>
                </Section>

                {/* ── Station 1 ──────────────────────────────── */}
                <Section
                  title="Station 1 — Measurement"
                  subtitle="Camera and caliper settings."
                >
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="Station name" {...field("s1.name")} />
                    <TextField
                      label="Offset from entry (pulses)"
                      {...numField("s1.station_offset_pulses")}
                    />
                    <TextField label="Camera id" {...field("s1.camera_id")} />
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="Camera IP" {...field("s1.camera.ip")} />
                    <TextField label="Vendor" {...field("s1.camera.vendor")} />
                    <TextField label="FPS" {...numField("s1.camera.fps")} />
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="Width" {...numField("s1.camera.resolution.x")} />
                    <TextField label="Height" {...numField("s1.camera.resolution.y")} />
                    <TextField
                      label="Strobe register"
                      {...numField("s1.camera.strobe_reg")}
                    />
                    <TextField
                      label="Strobe delay (ms)"
                      {...numField("s1.camera.strobe_capture_delay_ms")}
                    />
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="ROI x1" {...numField("s1.camera.roi.x1")} />
                    <TextField label="ROI y1" {...numField("s1.camera.roi.y1")} />
                    <TextField label="ROI x2" {...numField("s1.camera.roi.x2")} />
                    <TextField label="ROI y2" {...numField("s1.camera.roi.y2")} />
                  </Stack>
                  <FormControlLabel
                    control={<Switch {...toggle("s1.camera.sim.enabled")} />}
                    label="Read images from disk instead of the camera"
                  />
                  <TextField
                    label="Sim image path"
                    {...field("s1.camera.sim.image_path")}
                    sx={{ ...inputSx, mt: 1, mb: 2 }}
                    helperText="Required when simulation is on"
                  />
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                    <TextField select label="Method" {...field("s1.measurement.method")}>
                      <MenuItem value="caliper">caliper</MenuItem>
                      <MenuItem value="contour">contour</MenuItem>
                      <MenuItem value="ellipse">ellipse</MenuItem>
                    </TextField>
                    <TextField
                      label="Max ovality (mm)"
                      {...numField("s1.measurement.max_ovality")}
                    />
                    <TextField
                      label="Locator model path"
                      {...field("s1.measurement.model_path")}
                      helperText="Leave blank to measure the whole frame by contour"
                    />
                  </Stack>
                </Section>

                {/* ── Station 2 ──────────────────────────────── */}
                <Section
                  title="Station 2 — Defect Detection"
                  subtitle="Camera and model settings."
                >
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="Station name" {...field("s2.name")} />
                    <TextField
                      label="Offset from entry (pulses)"
                      {...numField("s2.station_offset_pulses")}
                    />
                    <TextField label="Camera id" {...field("s2.camera_id")} />
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="Camera IP" {...field("s2.camera.ip")} />
                    <TextField label="Vendor" {...field("s2.camera.vendor")} />
                    <TextField label="FPS" {...numField("s2.camera.fps")} />
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="Width" {...numField("s2.camera.resolution.x")} />
                    <TextField label="Height" {...numField("s2.camera.resolution.y")} />
                    <TextField
                      label="Strobe register"
                      {...numField("s2.camera.strobe_reg")}
                    />
                    <TextField
                      label="Strobe delay (ms)"
                      {...numField("s2.camera.strobe_capture_delay_ms")}
                    />
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="ROI x1" {...numField("s2.camera.roi.x1")} />
                    <TextField label="ROI y1" {...numField("s2.camera.roi.y1")} />
                    <TextField label="ROI x2" {...numField("s2.camera.roi.x2")} />
                    <TextField label="ROI y2" {...numField("s2.camera.roi.y2")} />
                  </Stack>
                  <FormControlLabel
                    control={<Switch {...toggle("s2.camera.sim.enabled")} />}
                    label="Read images from disk instead of the camera"
                  />
                  <TextField
                    label="Sim image path"
                    {...field("s2.camera.sim.image_path")}
                    sx={{ ...inputSx, mt: 1, mb: 2 }}
                    helperText="Required when simulation is on"
                  />
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                    <TextField
                      label="Defect model path"
                      {...field("s2.defect.model_path")}
                    />
                    <TextField select label="Model type" {...field("s2.defect.model_type")}>
                      <MenuItem value="yolo">yolo</MenuItem>
                      <MenuItem value="nanodet">nanodet</MenuItem>
                      <MenuItem value="onnx">onnx</MenuItem>
                      <MenuItem value="tensorrt">tensorrt</MenuItem>
                      <MenuItem value="torchvision">torchvision</MenuItem>
                    </TextField>
                    <TextField
                      label="Model conf. threshold"
                      {...numField("s2.defect.conf_thresh")}
                      helperText="Lowered automatically to the lowest per-defect threshold on the part"
                    />
                  </Stack>
                </Section>

                {/* ── Reject + Exit ──────────────────────────── */}
                <Section title="Reject &amp; Exit Stations">
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="Reject station name" {...field("r1.name")} />
                    <TextField
                      label="Reject offset (pulses)"
                      {...numField("r1.station_offset_pulses")}
                    />
                  </Stack>
                  <FormControlLabel
                    control={<Switch {...toggle("r1.enabled")} />}
                    label="Reject actuator wired — NOK parts are physically removed"
                    sx={{ mb: 2 }}
                  />
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }}>
                    <TextField label="Exit station name" {...field("exit1.name")} />
                    <TextField
                      label="Exit offset (pulses)"
                      {...numField("exit1.station_offset_pulses")}
                    />
                    {/* Spelling matters — config_loader accepts exactly these two. */}
                    <TextField select label="Pass if" {...field("exit1.pass_if")}>
                      <MenuItem value="all_stations_pass">all_stations_pass</MenuItem>
                      <MenuItem value="any_station_pass">any_station_pass</MenuItem>
                    </TextField>
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                    <TextField
                      label="part_id register"
                      {...numField("exit1.result_write.part_id_reg")}
                    />
                    <TextField
                      label="result register"
                      {...numField("exit1.result_write.result_reg")}
                    />
                    <TextField
                      label="ack register"
                      {...numField("exit1.result_write.ack_reg")}
                    />
                  </Stack>
                </Section>

                <Box sx={{ display: "flex", justifyContent: "flex-end", gap: 2, mt: 3 }}>
                  <Button variant="outlined" color="secondary" onClick={() => navigate(-1)}>
                    Cancel
                  </Button>
                  <Button
                    variant="contained"
                    size="large"
                    onClick={handleSave}
                    disabled={!canSave || saving || restoring}
                    sx={{ px: 4 }}
                  >
                    {saving ? "Saving…" : exists ? "Save Changes" : "Create Config"}
                  </Button>
                </Box>
              </Box>

              {meta.config_yaml && (
                <Box sx={{ mt: 3 }}>
                  <Section
                    title="Generated YAML"
                    subtitle={meta.config_path || "What is written to disk. Read-only."}
                  >
                    <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}>
                      <Button size="small" variant="outlined" onClick={handleDownload}>
                        Download YAML
                      </Button>
                    </Stack>
                    <Box
                      component="pre"
                      sx={{
                        m: 0,
                        p: 2,
                        maxHeight: 400,
                        overflow: "auto",
                        fontSize: 12,
                        bgcolor: "background.default",
                        border: 1,
                        borderColor: "divider",
                        borderRadius: 1,
                      }}
                    >
                      {meta.config_yaml}
                    </Box>
                  </Section>
                </Box>
              )}
            </>
          )}
        </Paper>
      </Box>

      {/* Restoring writes to the machine's config file, so it asks first. */}
      <Dialog open={confirmRestore} onClose={() => setConfirmRestore(false)}>
        <DialogTitle sx={{ fontWeight: 700 }}>
          Restore version {meta?.previous?.version}?
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary">
            The current config (version {meta?.version}) stays in the history — this
            saves the older one as a new version and writes it to disk.
          </Typography>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
          <Button
            onClick={() => setConfirmRestore(false)}
            sx={{ color: "text.secondary", textTransform: "none" }}
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleRestore}
            sx={{ textTransform: "none" }}
          >
            Restore
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={!!toast}
        autoHideDuration={10000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Alert
          severity={toast?.severity || "info"}
          variant="filled"
          onClose={() => setToast(null)}
          sx={{ width: "100%", maxWidth: 700 }}
        >
          {toast?.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default PartConfigPage;