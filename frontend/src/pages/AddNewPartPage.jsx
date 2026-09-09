import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Divider,
  FormControlLabel,
  IconButton,
  MenuItem,
  Snackbar,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import Autocomplete from "@mui/material/Autocomplete";
import { useTheme } from "@mui/material/styles";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import UploadFileIcon from "@mui/icons-material/UploadFile";

import api from "../api/axios";
import { useAuth } from "../auth/AuthContext";

// ─────────────────────────────────────────────────────────────────
// Endpoints. Reads come from the operator router, writes from the
// admin router — both mounted at /parts.
// ─────────────────────────────────────────────────────────────────
const EP = {
  categories: "/parts/categories",
  addCategory: "/parts/categories",
  addPart: "/parts",
  bulkUpload: "/parts/bulk-upload",
  bulkTemplate: "/parts/bulk-upload-template",
};

const SEVERITIES = ["critical", "major", "minor"];
const UNIT_OPTIONS = ["mm", "cm", "um", "deg", "mm2", ""];

// Part.defects  → { class_name: { conf_thresh, severity, notes } }
const emptyDefect = () => ({
  class_name: "",
  conf_thresh: "",
  severity: "critical",
  notes: "",
});

// Part.dimensions → { param_name: { nominal, upper_limit, lower_limit, unit, notes } }
const emptyDimension = () => ({
  param_name: "",
  nominal: "",
  upper_limit: "",
  lower_limit: "",
  unit: "mm",
  notes: "",
});

const numeric = (v) => v === "" || /^-?[0-9]*\.?[0-9]*$/.test(v);
const nonNegative = (v) => v === "" || /^[0-9]*\.?[0-9]*$/.test(v);

const inputSx = {
  "& .MuiOutlinedInput-root": {
    height: 44,
    borderRadius: 1.5,
    bgcolor: "background.paper",
  },
  "& .MuiOutlinedInput-input": { padding: "10px 12px", fontSize: "0.9rem" },
  "& .MuiInputLabel-root": { fontSize: "0.85rem" },
};

const persistentPrimary = (theme) => ({
  "&.Mui-disabled": {
    backgroundColor: theme.palette.primary.main,
    color: theme.palette.primary.contrastText,
    opacity: 0.55,
  },
});

const cardSx = {
  bgcolor: "background.paper",
  borderRadius: 2,
  p: { xs: 2, sm: 3, md: 4 },
  border: "1px solid",
  borderColor: "divider",
};

const Section = ({ title, subtitle, children }) => (
  <Box sx={{ mb: 3.5 }}>
    <Typography
      variant="subtitle2"
      sx={{ fontWeight: 700, color: "text.primary", mb: subtitle ? 0.25 : 1 }}
    >
      {title}
    </Typography>
    {subtitle && (
      <Typography
        variant="caption"
        sx={{ color: "text.secondary", display: "block", mb: 1.25 }}
      >
        {subtitle}
      </Typography>
    )}
    {children}
  </Box>
);

const AddNewPartPage = () => {
  const theme = useTheme();

  // Read the context rather than take a prop: the route renders this
  // component with no props, so a loginData prop is always undefined and
  // the whole form mounts disabled.
  const { user, isAdmin, isSuperAdmin } = useAuth();
  const role = user?.role;
  const canEdit = Boolean(isAdmin || isSuperAdmin);

  const [toast, setToast] = useState(null); // { severity, message }
  const notify = (severity, message) => setToast({ severity, message });

  // ── Categories ───────────────────────────────────────────────
  const [categories, setCategories] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [newCategory, setNewCategory] = useState("");
  const [addingCategory, setAddingCategory] = useState(false);

  // ── Basic fields ─────────────────────────────────────────────
  const [partName, setPartName] = useState("");
  const [partCode, setPartCode] = useState("");
  const [notes, setNotes] = useState("");
  const [partWeight, setPartWeight] = useState("");
  const [imageFile, setImageFile] = useState(null);

  // ── Optional config blocks ───────────────────────────────────
  const [wantDefects, setWantDefects] = useState(false);
  const [wantDimensions, setWantDimensions] = useState(false);
  const [defects, setDefects] = useState([emptyDefect()]);
  const [dimensions, setDimensions] = useState([emptyDimension()]);

  const [submitting, setSubmitting] = useState(false);

  // ── Bulk upload ──────────────────────────────────────────────
  const [uploadFile, setUploadFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [downloadingTemplate, setDownloadingTemplate] = useState(false);

  useEffect(() => {
    fetchCategories();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchCategories = async () => {
    try {
      const { data } = await api.get(EP.categories);
      setCategories(data);
    } catch {
      notify("error", "Failed to load categories.");
    }
  };

  const imagePreview = useMemo(
    () => (imageFile ? URL.createObjectURL(imageFile) : null),
    [imageFile],
  );
  useEffect(
    () => () => imagePreview && URL.revokeObjectURL(imagePreview),
    [imagePreview],
  );

  // ── Category creation ────────────────────────────────────────
  const handleAddCategory = async () => {
    const clean = newCategory.trim();
    if (!clean) return notify("error", "Type a category name first.");

    setAddingCategory(true);
    try {
      const { data } = await api.post(EP.addCategory, { category_name: clean });
      const created = {
        category_id: data.category_id,
        category_name: data.category_name,
      };
      setCategories((prev) =>
        prev.some((c) => c.category_id === created.category_id)
          ? prev
          : [...prev, created],
      );
      setSelectedCategory(created);
      setNewCategory("");
      notify("success", `Category "${created.category_name}" added.`);
    } catch (err) {
      notify("error", err?.response?.data?.detail || "Failed to add category.");
    } finally {
      setAddingCategory(false);
    }
  };

  // ── Defect rows ──────────────────────────────────────────────
  const addDefect = () => setDefects((d) => [...d, emptyDefect()]);
  const removeDefect = (i) =>
    setDefects((d) => (d.length === 1 ? d : d.filter((_, idx) => idx !== i)));
  const updateDefect = (i, field, value) =>
    setDefects((d) =>
      d.map((row, idx) => (idx === i ? { ...row, [field]: value } : row)),
    );

  // ── Dimension rows ───────────────────────────────────────────
  const addDimension = () => setDimensions((d) => [...d, emptyDimension()]);
  const removeDimension = (i) =>
    setDimensions((d) => (d.length === 1 ? d : d.filter((_, idx) => idx !== i)));
  const updateDimension = (i, field, value) =>
    setDimensions((d) =>
      d.map((row, idx) => (idx === i ? { ...row, [field]: value } : row)),
    );

  // ── Payload builders — exactly the JSON shapes in models.py ───
  const buildDefects = () => {
    const out = {};
    for (const d of defects) {
      const key = d.class_name.trim();
      if (!key) continue;
      out[key] = {
        conf_thresh: d.conf_thresh === "" ? null : Number(d.conf_thresh),
        severity: d.severity,
        notes: d.notes.trim(),
      };
    }
    return out;
  };

  const buildDimensions = () => {
    const out = {};
    for (const d of dimensions) {
      const key = d.param_name.trim();
      if (!key) continue;
      out[key] = {
        nominal: d.nominal === "" ? null : Number(d.nominal),
        upper_limit: d.upper_limit === "" ? null : Number(d.upper_limit),
        lower_limit: d.lower_limit === "" ? null : Number(d.lower_limit),
        unit: d.unit,
        notes: d.notes.trim(),
      };
    }
    return out;
  };

  // ── Validation ───────────────────────────────────────────────
  const validate = () => {
    if (!partName.trim()) return "Part Name is required.";
    if (!partCode.trim()) return "Part Code is required.";
    if (!selectedCategory) return "Select a category (or add a new one).";

    if (wantDefects) {
      const named = defects.filter((d) => d.class_name.trim());
      if (named.length === 0)
        return "Add at least one defect class, or untick Defect inspection.";
      const keys = named.map((d) => d.class_name.trim());
      const dupe = keys.find((k, i) => keys.indexOf(k) !== i);
      if (dupe) return `Duplicate defect class "${dupe}".`;
      for (const d of named) {
        if (d.conf_thresh !== "") {
          const v = Number(d.conf_thresh);
          if (v < 0 || v > 1)
            return `${d.class_name}: confidence threshold must be between 0 and 1.`;
        }
      }
    }

    if (wantDimensions) {
      const named = dimensions.filter((d) => d.param_name.trim());
      if (named.length === 0)
        return "Add at least one dimension, or untick Measurement.";
      const keys = named.map((d) => d.param_name.trim());
      const dupe = keys.find((k, i) => keys.indexOf(k) !== i);
      if (dupe) return `Duplicate dimension "${dupe}".`;
      for (const d of named) {
        const { lower_limit: lo, upper_limit: hi, nominal: nom } = d;
        if (lo !== "" && hi !== "" && Number(lo) > Number(hi))
          return `${d.param_name}: lower limit is above the upper limit.`;
        if (nom !== "" && lo !== "" && Number(nom) < Number(lo))
          return `${d.param_name}: nominal is below the lower limit.`;
        if (nom !== "" && hi !== "" && Number(nom) > Number(hi))
          return `${d.param_name}: nominal is above the upper limit.`;
      }
    }
    return null;
  };

  const resetForm = () => {
    setPartName("");
    setPartCode("");
    setNotes("");
    setPartWeight("");
    setImageFile(null);
    setSelectedCategory(null);
    setNewCategory("");
    setWantDefects(false);
    setWantDimensions(false);
    setDefects([emptyDefect()]);
    setDimensions([emptyDimension()]);
    const el = document.getElementById("osm-part-image-input");
    if (el) el.value = null;
  };

  const handleSubmit = async () => {
    const err = validate();
    if (err) return notify("error", err);

    const fd = new FormData();
    fd.append("part_name", partName.trim());
    fd.append("part_code", partCode.trim());
    fd.append("category_id", selectedCategory.category_id);
    if (notes.trim()) fd.append("notes", notes.trim());
    if (partWeight !== "") fd.append("part_weight", Number(partWeight));

    // has_defect_pipeline / has_measurement_pipeline are intentionally NOT
    // sent — the backend sets them when a PartConfig is saved from the
    // pipeline builder. This form only supplies the parameter tables.
    if (wantDefects) fd.append("defects", JSON.stringify(buildDefects()));
    if (wantDimensions) fd.append("dimensions", JSON.stringify(buildDimensions()));

    if (imageFile) fd.append("image", imageFile);

    setSubmitting(true);
    try {
      const { data } = await api.post(EP.addPart, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      notify(
        "success",
        `Part created — ${partCode.trim()}${data?.part_id ? ` (id ${data.part_id})` : ""}. Build its pipeline next.`,
      );
      resetForm();
      fetchCategories();
    } catch (e) {
      notify("error", e?.response?.data?.detail || "Failed to create part.");
    } finally {
      setSubmitting(false);
    }
  };

  // ── Bulk upload handlers ─────────────────────────────────────
  const clearUploadFile = () => {
    setUploadFile(null);
    const el = document.getElementById("osm-bulk-file-input");
    if (el) el.value = null;
  };

  const handleBulkUpload = async () => {
    if (!uploadFile) return notify("error", "Select a CSV or Excel file first.");
    if (!/\.(csv|xlsx)$/i.test(uploadFile.name))
      return notify("error", "Only .csv and .xlsx files are supported.");

    setUploading(true);
    setUploadResult(null);
    const fd = new FormData();
    fd.append("file", uploadFile);

    try {
      const { data } = await api.post(EP.bulkUpload, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadResult(data);
      clearUploadFile();
      fetchCategories();

      const created = data?.created_parts ?? 0;
      const errCount = data?.errors?.length ?? 0;
      notify(
        errCount ? "warning" : "success",
        `Imported ${created} part${created === 1 ? "" : "s"}` +
          (errCount ? ` — ${errCount} issue${errCount === 1 ? "" : "s"} to review.` : "."),
      );
    } catch (e) {
      notify("error", e?.response?.data?.detail || "Bulk upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleTemplateDownload = async () => {
    setDownloadingTemplate(true);
    try {
      const res = await api.get(EP.bulkTemplate, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = "OSM_BulkUpload_Template.xlsx";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch {
      notify("error", "Failed to download the template.");
    } finally {
      setDownloadingTemplate(false);
    }
  };

  return (
    <Box
      sx={{
        height: "100%",
        minHeight: 0,
        overflowY: "auto",
        bgcolor: "background.default",
      }}
    >
      <Box
        sx={{
          maxWidth: 1100,
          mx: "auto",
          px: { xs: 1.5, sm: 3, md: 4 },
          py: { xs: 2, md: 3 },
        }}
      >
        {/* Only reachable if this page is ever rendered outside RequireAdmin. */}
        {!canEdit && (
          <Alert severity="warning" sx={{ mb: 3 }}>
            Creating parts requires administrator rights. You are signed in as{" "}
            <b>{role || "an operator"}</b>.
          </Alert>
        )}

        {/* ════════ BULK UPLOAD ════════════════════════════════ */}
        <Box sx={{ ...cardSx, mb: 3 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
            <UploadFileIcon color="primary" />
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              Bulk Part Upload
            </Typography>
          </Stack>
          <Typography variant="body2" sx={{ color: "text.secondary", mb: 2 }}>
            The template has three sheets. <b>Parts</b> carries one row per part;{" "}
            <b>Dimensions</b> and <b>Defects</b> carry one row per parameter,
            joined back by <code>part_code</code>. A CSV imports the Parts sheet
            only — parameters need the workbook.
          </Typography>

          <Box
            component="fieldset"
            disabled={!canEdit}
            sx={{ border: 0, p: 0, m: 0, minWidth: 0 }}
          >
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={1.5}
              sx={{ flexWrap: "wrap" }}
            >
              <Button
                variant="contained"
                color="primary"
                component="label"
                disabled={!canEdit}
                sx={persistentPrimary(theme)}
              >
                Select File
                <input
                  id="osm-bulk-file-input"
                  type="file"
                  accept=".xlsx,.csv"
                  hidden
                  disabled={!canEdit}
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                />
              </Button>
              <Button
                variant="contained"
                color="primary"
                onClick={handleBulkUpload}
                disabled={!canEdit || uploading || !uploadFile}
                sx={persistentPrimary(theme)}
              >
                {uploading ? "Uploading…" : "Import File"}
              </Button>
              <Button
                variant="outlined"
                color="primary"
                onClick={handleTemplateDownload}
                disabled={downloadingTemplate}
              >
                {downloadingTemplate ? "Preparing…" : "Download Template"}
              </Button>
            </Stack>

            {uploadFile && (
              <Chip
                label={uploadFile.name}
                onDelete={clearUploadFile}
                sx={{ mt: 1.5, maxWidth: "100%" }}
              />
            )}

            {uploadResult && (
              <Box
                sx={{
                  mt: 2,
                  p: 2,
                  borderRadius: 1.5,
                  border: 1,
                  borderColor: "divider",
                  bgcolor: "background.default",
                }}
              >
                <Typography sx={{ fontWeight: 700, mb: 0.75 }}>
                  Import finished
                </Typography>
                <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
                  <Chip
                    size="small"
                    color="success"
                    label={`Created: ${uploadResult.created_parts ?? 0}`}
                  />
                  <Chip
                    size="small"
                    label={`With dimensions: ${uploadResult.with_dimensions ?? 0}`}
                  />
                  <Chip
                    size="small"
                    label={`With defects: ${uploadResult.with_defects ?? 0}`}
                  />
                  {uploadResult.errors?.length > 0 && (
                    <Chip
                      size="small"
                      color="error"
                      label={`Issues: ${uploadResult.errors.length}`}
                    />
                  )}
                </Stack>

                {uploadResult.errors?.length > 0 && (
                  <Box sx={{ mt: 1.5, maxHeight: 180, overflowY: "auto", pr: 1 }}>
                    {uploadResult.errors.map((msg, i) => (
                      <Typography
                        key={i}
                        variant="caption"
                        color="error"
                        sx={{ display: "block" }}
                      >
                        • {msg}
                      </Typography>
                    ))}
                  </Box>
                )}
              </Box>
            )}
          </Box>
        </Box>

        {/* ════════ SINGLE PART ════════════════════════════════ */}
        <Box sx={cardSx}>
          <Typography variant="h6" sx={{ fontWeight: 700, mb: 0.5 }}>
            Add Single Part
          </Typography>
          <Typography variant="body2" sx={{ color: "text.secondary", mb: 2.5 }}>
            Fields marked * are required. Defect and measurement parameters are
            optional here — the pipeline builder activates them later.
          </Typography>

          <Box
            component="fieldset"
            disabled={!canEdit || submitting}
            sx={{ border: 0, p: 0, m: 0, minWidth: 0 }}
          >
            {/* ── Basic information ─────────────────────────────── */}
            <Section title="Basic Information">
              <Stack spacing={2}>
                <Autocomplete
                  fullWidth
                  options={categories}
                  value={selectedCategory}
                  getOptionLabel={(o) => o?.category_name || ""}
                  isOptionEqualToValue={(o, v) => o?.category_id === v?.category_id}
                  onChange={(e, v) => setSelectedCategory(v)}
                  disabled={!canEdit || !!newCategory.trim()}
                  renderInput={(p) => (
                    <TextField
                      {...p}
                      label="Category *"
                      sx={inputSx}
                      helperText={
                        newCategory.trim()
                          ? "Clear the new-category field to use the dropdown"
                          : " "
                      }
                    />
                  )}
                />

                <Stack
                  direction={{ xs: "column", sm: "row" }}
                  spacing={1.5}
                  alignItems="flex-start"
                >
                  <TextField
                    fullWidth
                    label="Add New Category"
                    value={newCategory}
                    disabled={!canEdit || !!selectedCategory}
                    onChange={(e) => setNewCategory(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleAddCategory()}
                    helperText={
                      selectedCategory
                        ? "Clear the dropdown to add a new category"
                        : " "
                    }
                    sx={inputSx}
                  />
                  <Button
                    variant="contained"
                    color="primary"
                    onClick={handleAddCategory}
                    disabled={
                      !canEdit ||
                      !!selectedCategory ||
                      !newCategory.trim() ||
                      addingCategory
                    }
                    sx={{
                      whiteSpace: "nowrap",
                      height: 44,
                      ...persistentPrimary(theme),
                    }}
                  >
                    {addingCategory ? "Adding…" : "Add Category"}
                  </Button>
                </Stack>

                <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                  <TextField
                    fullWidth
                    label="Part Name *"
                    value={partName}
                    onChange={(e) => setPartName(e.target.value)}
                    sx={inputSx}
                  />
                  <TextField
                    fullWidth
                    label="Part Code *"
                    value={partCode}
                    onChange={(e) => setPartCode(e.target.value)}
                    inputProps={{ maxLength: 50 }}
                    helperText="Unique, max 50 characters — this is what the barcode scanner reads."
                    sx={inputSx}
                  />
                </Stack>

                <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                  <TextField
                    label="Part Weight (g)"
                    value={partWeight}
                    onChange={(e) =>
                      nonNegative(e.target.value) && setPartWeight(e.target.value)
                    }
                    inputProps={{ inputMode: "decimal" }}
                    sx={{ ...inputSx, maxWidth: { sm: 260 }, width: "100%" }}
                  />
                  <TextField
                    fullWidth
                    label="Notes (optional)"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    sx={inputSx}
                  />
                </Stack>
              </Stack>
            </Section>

            <Divider sx={{ mb: 3 }} />

            {/* ── What this part is inspected for ───────────────── */}
            <Section
              title="Inspection Parameters"
              subtitle="Tick what this part needs. The pipeline flags themselves are set by the backend when you save a pipeline config for this part."
            >
              <Box sx={{ display: "flex", flexWrap: "wrap", gap: { xs: 1, sm: 3 } }}>
                <FormControlLabel
                  label="Defect inspection"
                  control={
                    <Checkbox
                      color="primary"
                      checked={wantDefects}
                      onChange={(e) => setWantDefects(e.target.checked)}
                    />
                  }
                />
                <FormControlLabel
                  label="Measurement"
                  control={
                    <Checkbox
                      color="primary"
                      checked={wantDimensions}
                      onChange={(e) => setWantDimensions(e.target.checked)}
                    />
                  }
                />
              </Box>
            </Section>

            {/* ── Defects ───────────────────────────────────────── */}
            {wantDefects && (
              <>
                <Divider sx={{ mb: 3 }} />
                <Section
                  title="Defect Classes"
                  subtitle="The class name is the dictionary key in Part.defects and must match the detection model's class name exactly (e.g. rust, crack, scratch)."
                >
                  {defects.map((d, i) => (
                    <Box
                      key={i}
                      sx={{
                        display: "grid",
                        gridTemplateColumns: {
                          xs: "1fr",
                          md: "1.2fr 0.8fr 0.9fr 1.4fr auto",
                        },
                        gap: 1,
                        mb: 1.5,
                        alignItems: "center",
                      }}
                    >
                      <TextField
                        label="Class name *"
                        value={d.class_name}
                        onChange={(e) => updateDefect(i, "class_name", e.target.value)}
                        sx={inputSx}
                      />
                      <TextField
                        label="Conf. threshold"
                        value={d.conf_thresh}
                        placeholder="0.70"
                        inputProps={{ inputMode: "decimal" }}
                        onChange={(e) =>
                          nonNegative(e.target.value) &&
                          updateDefect(i, "conf_thresh", e.target.value)
                        }
                        sx={inputSx}
                      />
                      <TextField
                        select
                        label="Severity"
                        value={d.severity}
                        onChange={(e) => updateDefect(i, "severity", e.target.value)}
                        sx={inputSx}
                      >
                        {SEVERITIES.map((s) => (
                          <MenuItem key={s} value={s}>
                            {s}
                          </MenuItem>
                        ))}
                      </TextField>
                      <TextField
                        label="Notes"
                        value={d.notes}
                        onChange={(e) => updateDefect(i, "notes", e.target.value)}
                        sx={inputSx}
                      />
                      <IconButton
                        size="small"
                        disabled={defects.length === 1}
                        onClick={() => removeDefect(i)}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Box>
                  ))}
                  <Button size="small" color="primary" onClick={addDefect}>
                    + Add another defect class
                  </Button>
                </Section>
              </>
            )}

            {/* ── Dimensions ────────────────────────────────────── */}
            {wantDimensions && (
              <>
                <Divider sx={{ mb: 3 }} />
                <Section
                  title="Measurement Parameters"
                  subtitle="The parameter name is the dictionary key in Part.dimensions — use the same name the measurement step emits (e.g. diameter_mm, length_mm)."
                >
                  {dimensions.map((d, i) => (
                    <Box
                      key={i}
                      sx={{
                        border: 1,
                        borderColor: "divider",
                        borderRadius: 1.5,
                        p: 2,
                        mb: 2,
                      }}
                    >
                      <Stack
                        direction="row"
                        justifyContent="space-between"
                        alignItems="center"
                        sx={{ mb: 1.5 }}
                      >
                        <Chip
                          size="small"
                          label={d.param_name.trim() || `parameter ${i + 1}`}
                          sx={{ fontWeight: 600 }}
                        />
                        <IconButton
                          size="small"
                          disabled={dimensions.length === 1}
                          onClick={() => removeDimension(i)}
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </Stack>

                      <Box
                        sx={{
                          display: "grid",
                          gridTemplateColumns: {
                            xs: "1fr",
                            sm: "1fr 1fr",
                            md: "1.4fr 0.8fr 0.8fr 0.8fr 0.7fr",
                          },
                          gap: 1,
                        }}
                      >
                        <TextField
                          label="Parameter name *"
                          value={d.param_name}
                          placeholder="diameter_mm"
                          onChange={(e) =>
                            updateDimension(i, "param_name", e.target.value)
                          }
                          sx={inputSx}
                        />
                        <TextField
                          label="Nominal"
                          value={d.nominal}
                          inputProps={{ inputMode: "decimal" }}
                          onChange={(e) =>
                            numeric(e.target.value) &&
                            updateDimension(i, "nominal", e.target.value)
                          }
                          sx={inputSx}
                        />
                        <TextField
                          label="Lower limit"
                          value={d.lower_limit}
                          inputProps={{ inputMode: "decimal" }}
                          onChange={(e) =>
                            numeric(e.target.value) &&
                            updateDimension(i, "lower_limit", e.target.value)
                          }
                          sx={inputSx}
                        />
                        <TextField
                          label="Upper limit"
                          value={d.upper_limit}
                          inputProps={{ inputMode: "decimal" }}
                          onChange={(e) =>
                            numeric(e.target.value) &&
                            updateDimension(i, "upper_limit", e.target.value)
                          }
                          sx={inputSx}
                        />
                        <TextField
                          select
                          label="Unit"
                          value={d.unit}
                          onChange={(e) => updateDimension(i, "unit", e.target.value)}
                          sx={inputSx}
                        >
                          {UNIT_OPTIONS.map((u) => (
                            <MenuItem key={u || "none"} value={u}>
                              {u || "— none —"}
                            </MenuItem>
                          ))}
                        </TextField>
                      </Box>

                      <TextField
                        fullWidth
                        label="Notes"
                        value={d.notes}
                        onChange={(e) => updateDimension(i, "notes", e.target.value)}
                        sx={{ ...inputSx, mt: 1 }}
                      />
                    </Box>
                  ))}
                  <Button size="small" color="primary" onClick={addDimension}>
                    + Add another parameter
                  </Button>
                </Section>
              </>
            )}

            <Divider sx={{ mb: 3 }} />

            {/* ── Image ─────────────────────────────────────────── */}
            <Section title="Part Image">
              <Button
                variant="outlined"
                color="primary"
                component="label"
                disabled={!canEdit}
              >
                Upload Image (PNG / JPEG)
                <input
                  id="osm-part-image-input"
                  type="file"
                  accept="image/png,image/jpeg"
                  hidden
                  disabled={!canEdit}
                  onChange={(e) => setImageFile(e.target.files?.[0] || null)}
                />
              </Button>
              {imageFile && (
                <Stack
                  direction="row"
                  spacing={1.5}
                  alignItems="center"
                  sx={{ mt: 1.5 }}
                >
                  <img
                    src={imagePreview}
                    alt="preview"
                    style={{
                      width: 110,
                      height: 110,
                      objectFit: "cover",
                      borderRadius: 8,
                      border: "1px solid",
                      borderColor: theme.palette.divider,
                    }}
                  />
                  <Chip label={imageFile.name} onDelete={() => setImageFile(null)} />
                </Stack>
              )}
            </Section>

            <Box
              sx={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 2,
                pt: 2,
                borderTop: 1,
                borderColor: "divider",
              }}
            >
              <Button
                variant="outlined"
                color="secondary"
                onClick={resetForm}
                disabled={!canEdit}
              >
                Reset
              </Button>
              <Button
                variant="contained"
                color="primary"
                size="large"
                onClick={handleSubmit}
                disabled={!canEdit || submitting}
                sx={{ px: 4, ...persistentPrimary(theme) }}
              >
                {submitting ? "Saving…" : "Save Part"}
              </Button>
            </Box>
          </Box>
        </Box>
      </Box>

      <Snackbar
        open={!!toast}
        autoHideDuration={5000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Alert
          severity={toast?.severity || "info"}
          variant="filled"
          onClose={() => setToast(null)}
          sx={{ width: "100%" }}
        >
          {toast?.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default AddNewPartPage;