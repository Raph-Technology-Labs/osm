import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  MenuItem,
  Snackbar,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import Autocomplete from "@mui/material/Autocomplete";
import { useTheme } from "@mui/material/styles";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { useNavigate } from "react-router-dom";

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

const UNIT_OPTIONS = ["mm", "cm", "um", "deg", "mm2", ""];

// Part.defects → { <defect name>: { conf_thresh } }
// The name is typed free-hand: a fixed list would imply the machine only
// ever checks for those defects, when the real list is whatever the
// detection model was trained on for this part.
const emptyDefect = () => ({ defect_name: "", conf_thresh: "" });

// Part.dimensions → { <parameter name>: { nominal, lower_limit, upper_limit,
//                                          unit, calibration_factor } }
const emptyDimension = () => ({
  param_name: "",
  nominal: "",
  lower_limit: "",
  upper_limit: "",
  unit: "mm",
  calibration_factor: "",
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
  boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
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
  const navigate = useNavigate();

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
  const [weight, setWeight] = useState("");
  const [imageFile, setImageFile] = useState(null);

  // ── Parameter tables — both optional, filled in as needed ────
  const [defects, setDefects] = useState([emptyDefect()]);
  const [dimensions, setDimensions] = useState([emptyDimension()]);

  const [submitting, setSubmitting] = useState(false);

  // The part just created, so we can offer its config next. A new part
  // cannot run a session until it has one.
  const [createdPart, setCreatedPart] = useState(null); // { id, code }

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
    if (!clean) return notify("error", "Please type a category name.");

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

  // ── Defects ──────────────────────────────────────────────────
  const addDefect = () => setDefects((d) => [...d, emptyDefect()]);
  const removeDefect = (idx) =>
    setDefects((d) => (idx === 0 ? d : d.filter((_, i) => i !== idx)));
  const updateDefect = (idx, field, value) =>
    setDefects((d) =>
      d.map((item, i) => (i === idx ? { ...item, [field]: value } : item)),
    );

  // ── Dimensions ───────────────────────────────────────────────
  const addDimension = () => setDimensions((d) => [...d, emptyDimension()]);
  const removeDimension = (idx) =>
    setDimensions((d) => (idx === 0 ? d : d.filter((_, i) => i !== idx)));
  const updateDimension = (idx, field, value) =>
    setDimensions((d) =>
      d.map((item, i) => (i === idx ? { ...item, [field]: value } : item)),
    );

  // ── Payload builders — the JSON shapes in models.py ──────────
  const buildDefectPayload = () => {
    const out = {};
    defects.forEach((d) => {
      const key = d.defect_name.trim();
      if (!key) return;
      out[key] = {
        ...(d.conf_thresh !== "" && { conf_thresh: Number(d.conf_thresh) }),
      };
    });
    return out;
  };

  const buildDimensionPayload = () => {
    const out = {};
    dimensions.forEach((d) => {
      const key = d.param_name.trim();
      if (!key) return;
      out[key] = {
        ...(d.nominal !== "" && { nominal: Number(d.nominal) }),
        ...(d.lower_limit !== "" && { lower_limit: Number(d.lower_limit) }),
        ...(d.upper_limit !== "" && { upper_limit: Number(d.upper_limit) }),
        ...(d.unit && { unit: d.unit }),
        ...(d.calibration_factor !== "" && {
          calibration_factor: Number(d.calibration_factor),
        }),
      };
    });
    return out;
  };

  // ── Validation ───────────────────────────────────────────────
  // Both tables are optional; only rows with a name are checked, and blank
  // rows are ignored entirely.
  const validate = () => {
    if (!partName.trim() || !partCode.trim() || !selectedCategory)
      return "Please fill Part Name, Part Code and select or add a Category.";

    const namedDefects = defects.filter((d) => d.defect_name.trim());
    const defectKeys = namedDefects.map((d) => d.defect_name.trim());
    const dupeDefect = defectKeys.find((k, i) => defectKeys.indexOf(k) !== i);
    if (dupeDefect) return `Duplicate defect "${dupeDefect}".`;

    for (const d of namedDefects) {
      if (d.conf_thresh !== "") {
        const v = Number(d.conf_thresh);
        if (v < 0 || v > 1)
          return `${d.defect_name}: confidence threshold must be between 0 and 1.`;
      }
    }

    const namedDims = dimensions.filter((d) => d.param_name.trim());
    const dimKeys = namedDims.map((d) => d.param_name.trim());
    const dupeDim = dimKeys.find((k, i) => dimKeys.indexOf(k) !== i);
    if (dupeDim) return `Duplicate parameter "${dupeDim}".`;

    for (const d of namedDims) {
      const { lower_limit: lo, upper_limit: hi, nominal: nom } = d;
      if (lo === "" && hi === "")
        return `${d.param_name}: set at least a lower or upper tolerance — a parameter with no limits can never fail.`;
      if (lo !== "" && hi !== "" && Number(lo) > Number(hi))
        return `${d.param_name}: lower tolerance cannot be greater than upper.`;
      if (nom !== "" && lo !== "" && Number(nom) < Number(lo))
        return `${d.param_name}: nominal is below the lower tolerance.`;
      if (nom !== "" && hi !== "" && Number(nom) > Number(hi))
        return `${d.param_name}: nominal is above the upper tolerance.`;
      // A zero factor would zero out every measurement for this parameter.
      if (d.calibration_factor !== "" && Number(d.calibration_factor) <= 0)
        return `${d.param_name}: calibration factor must be greater than 0.`;
    }

    return null;
  };

  const resetForm = () => {
    setPartName("");
    setPartCode("");
    setNotes("");
    setWeight("");
    setDefects([emptyDefect()]);
    setDimensions([emptyDimension()]);
    setSelectedCategory(null);
    setNewCategory("");
    setImageFile(null);
    const el = document.getElementById("single-image-input");
    if (el) el.value = null;
  };

  const handleAddPart = async () => {
    const err = validate();
    if (err) return notify("error", err);

    const code = partCode.trim();
    const fd = new FormData();
    fd.append("part_name", partName.trim());
    fd.append("part_code", code);
    fd.append("category_id", selectedCategory.category_id);
    if (notes.trim()) fd.append("notes", notes.trim());
    if (weight !== "" && !isNaN(Number(weight))) fd.append("part_weight", weight);

    // has_defect_pipeline / has_measurement_pipeline are intentionally NOT
    // sent — the backend sets them when the machine config is saved. This
    // form only supplies the parameter tables.
    const defectPayload = buildDefectPayload();
    if (Object.keys(defectPayload).length)
      fd.append("defects", JSON.stringify(defectPayload));

    const dimensionPayload = buildDimensionPayload();
    if (Object.keys(dimensionPayload).length)
      fd.append("dimensions", JSON.stringify(dimensionPayload));

    if (imageFile) fd.append("image", imageFile);

    setSubmitting(true);
    try {
      const { data } = await api.post(EP.addPart, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      notify("success", `Part added! ID: ${data.part_id}`);
      setCreatedPart({ id: data.part_id, code });
      resetForm();
      fetchCategories();
    } catch (e) {
      notify("error", e?.response?.data?.detail || "Failed to add part.");
    } finally {
      setSubmitting(false);
    }
  };

  // ── Bulk upload ──────────────────────────────────────────────
  const clearUploadFile = () => {
    setUploadFile(null);
    const el = document.getElementById("bulk-file-input");
    if (el) el.value = null;
  };

  const handleBulkUpload = async () => {
    if (!uploadFile)
      return notify("error", "Please select a CSV or Excel file first.");
    if (!/\.(csv|xlsx)$/i.test(uploadFile.name))
      return notify("error", "Please upload only CSV or Excel files.");

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
        `Uploaded ✅ parts: ${created}` + (errCount ? `, issues: ${errCount}` : ""),
      );
    } catch (e) {
      notify("error", e?.response?.data?.detail || "Bulk upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const startTemplateDownload = async () => {
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
      notify("error", "Failed to download template.");
    } finally {
      setDownloadingTemplate(false);
    }
  };

  const newCategoryActive = newCategory.trim().length > 0;
  const dropdownDisabled = !canEdit || newCategoryActive;
  const newCategoryDisabled = !canEdit || !!selectedCategory;

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
          maxWidth: 1200,
          mx: "auto",
          px: { xs: 1.5, sm: 3, md: 4 },
          py: { xs: 2, md: 3 },
        }}
      >
        {/* Page header. Both admin roles reach the config page from here —
            what differs is what they may do once there: a superadministrator
            creates a config for a part that has none, an administrator only
            edits one that already exists. The label says which. */}
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1.5}
          alignItems={{ xs: "flex-start", sm: "center" }}
          justifyContent="space-between"
          sx={{ mb: 3 }}
        >
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Parts
            </Typography>
            <Typography variant="body2" sx={{ color: "text.secondary" }}>
              Add parts individually or in bulk, and configure the machine for
              each one.
            </Typography>
          </Box>

                    {canEdit && (
            <Tooltip
              title={
                isSuperAdmin
                  ? "Create a config for a new part, or edit an existing one"
                  : "Edit an existing part's machine config — only a superadministrator can create one"
              }
            >
              <Button
                variant="contained"
                startIcon={<SettingsOutlinedIcon />}
                onClick={() => navigate("/part-config")}
                sx={{
                  whiteSpace: "nowrap",
                  bgcolor: "common.black",
                  color: "common.white",
                  "&:hover": { bgcolor: "grey.800" },
                }}
              >
                Machine Config
              </Button>
            </Tooltip>
          )}
        </Stack>

        {/* Only reachable if this page is ever rendered outside RequireAdmin. */}
        {!canEdit && (
          <Alert severity="warning" sx={{ mb: 3 }}>
            Creating parts requires administrator rights. You are signed in as{" "}
            <b>{role || "an operator"}</b>.
          </Alert>
        )}

        {/* A part with no machine config cannot run a session, so the next
            step is offered here rather than left for the operator to
            discover at Start Session. */}
        {createdPart && (
          <Alert
            severity="success"
            sx={{ mb: 3 }}
            onClose={() => setCreatedPart(null)}
            action={
              <Button
                color="inherit"
                size="small"
                onClick={() => navigate(`/part-config/${createdPart.id}`)}
              >
                MACHINE CONFIG
              </Button>
            }
          >
            <b>{createdPart.code}</b> created. It needs a machine config before a
            session can run
            {!isSuperAdmin && " — a superadministrator has to create that"}.
          </Alert>
        )}

        {/* ===== Bulk Upload ===== */}
        <Box sx={{ ...cardSx, p: { xs: 2, sm: 3 }, mb: 3 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
            <UploadFileIcon color="primary" />
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              Bulk Part Upload
            </Typography>
          </Stack>
          <Typography variant="body2" sx={{ color: "text.secondary", mb: 2 }}>
            One row per part. Defects go in <code>d1_name</code> /{" "}
            <code>d1_threshold</code>, measurement parameters in{" "}
            <code>p1_name</code> / <code>p1_nominal</code> / <code>p1_min</code> /{" "}
            <code>p1_max</code> / <code>p1_unit</code> / <code>p1_cal</code>. The
            template has two slots of each — add <code>d3_*</code> or{" "}
            <code>p3_*</code> columns yourself for parts that need more.
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
                  id="bulk-file-input"
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
                {uploading ? "Uploading..." : "Submit File"}
              </Button>
              <Button
                variant="outlined"
                color="primary"
                onClick={startTemplateDownload}
                disabled={downloadingTemplate}
              >
                {downloadingTemplate ? "Preparing..." : "Download Template"}
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
                <Typography sx={{ fontWeight: 700, mb: 0.5 }}>
                  Import finished
                </Typography>
                <Typography variant="body2">
                  Created parts: {uploadResult.created_parts ?? 0}
                </Typography>
                <Typography variant="body2">
                  With dimensions: {uploadResult.with_dimensions ?? 0}
                </Typography>
                <Typography variant="body2">
                  With defects: {uploadResult.with_defects ?? 0}
                </Typography>
                {/* Bulk-imported parts have no machine config either. */}
                {(uploadResult.created_parts ?? 0) > 0 && (
                  <Typography variant="body2" sx={{ mt: 1, fontStyle: "italic" }}>
                    Each imported part still needs a machine config before it can
                    run a session.
                  </Typography>
                )}
                {uploadResult.errors?.length > 0 && (
                  <Box sx={{ mt: 1, maxHeight: 180, overflowY: "auto", pr: 1 }}>
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

        {/* ===== Add Single Part ===== */}
        <Box sx={{ ...cardSx, p: { xs: 2, sm: 3, md: 4 } }}>
          <Typography variant="h6" sx={{ fontWeight: 700, mb: 0.5 }}>
            ➕ Add Single Part
          </Typography>
          <Typography variant="body2" sx={{ color: "text.secondary", mb: 3 }}>
            Fields marked * are required. Add the defects this part is checked
            for, the dimensions it is measured on, or both — leave a table blank
            if it does not apply.
          </Typography>

          <Box
            component="fieldset"
            disabled={!canEdit || submitting}
            sx={{ border: 0, p: 0, m: 0, minWidth: 0 }}
          >
            <Section title="Basic Information">
              <Stack spacing={2}>
                <Autocomplete
                  options={categories}
                  value={selectedCategory}
                  disabled={dropdownDisabled}
                  getOptionLabel={(o) => o?.category_name || ""}
                  isOptionEqualToValue={(o, v) => o?.category_id === v?.category_id}
                  onChange={(e, v) => setSelectedCategory(v)}
                  renderInput={(p) => (
                    <TextField
                      {...p}
                      label="Select Category *"
                      helperText={
                        newCategoryActive
                          ? "Clear the new-category field to use the dropdown"
                          : " "
                      }
                      sx={inputSx}
                    />
                  )}
                />

                <Stack
                  direction={{ xs: "column", sm: "row" }}
                  spacing={1.5}
                  alignItems={{ sm: "flex-start" }}
                >
                  <TextField
                    fullWidth
                    label="Add New Category"
                    value={newCategory}
                    disabled={newCategoryDisabled}
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
                      newCategoryDisabled || !newCategory.trim() || addingCategory
                    }
                    sx={{
                      whiteSpace: "nowrap",
                      height: 44,
                      ...persistentPrimary(theme),
                    }}
                  >
                    {addingCategory ? "Adding..." : "Add Category"}
                  </Button>
                </Stack>

                <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                  <TextField
                    fullWidth
                    label="Part Name *"
                    value={partName}
                    sx={inputSx}
                    onChange={(e) => setPartName(e.target.value)}
                  />
                  <TextField
                    fullWidth
                    label="Part Code *"
                    value={partCode}
                    sx={inputSx}
                    inputProps={{ maxLength: 50 }}
                    helperText="Unique, max 50 characters — this is what the barcode scanner reads."
                    onChange={(e) => setPartCode(e.target.value)}
                  />
                </Stack>

                <TextField
                  fullWidth
                  label="Notes (optional)"
                  value={notes}
                  sx={inputSx}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </Stack>
            </Section>

            <Divider sx={{ mb: 3 }} />

            {/* ----- Weight ----- */}
            <Section title="Weight">
              <TextField
                label="Weight (g)"
                value={weight}
                sx={{ ...inputSx, maxWidth: 260 }}
                inputProps={{ inputMode: "decimal" }}
                onChange={(e) =>
                  nonNegative(e.target.value) && setWeight(e.target.value)
                }
              />
            </Section>

            <Divider sx={{ mb: 3 }} />

            {/* ----- Defects ----- */}
            <Section
              title="Defects"
              subtitle="Add each defect this part should be checked for, with an optional confidence threshold. The name must match the detection model's class name exactly."
            >
              {defects.map((d, i) => (
                <Box
                  key={i}
                  sx={{
                    display: "grid",
                    gridTemplateColumns: "auto 1fr 1fr auto",
                    gap: 1,
                    mb: 1,
                    alignItems: "center",
                  }}
                >
                  <Typography
                    variant="caption"
                    sx={{ color: "text.secondary", minWidth: 30 }}
                  >
                    d{i + 1}
                  </Typography>
                  <TextField
                    label="Defect name"
                    value={d.defect_name}
                    sx={inputSx}
                    onChange={(e) => updateDefect(i, "defect_name", e.target.value)}
                  />
                  <TextField
                    label="Confidence threshold"
                    value={d.conf_thresh}
                    sx={inputSx}
                    inputProps={{ inputMode: "decimal" }}
                    onChange={(e) =>
                      nonNegative(e.target.value) &&
                      updateDefect(i, "conf_thresh", e.target.value)
                    }
                  />
                  {i > 0 && (
                    <IconButton size="small" onClick={() => removeDefect(i)}>
                      ✕
                    </IconButton>
                  )}
                </Box>
              ))}
              <Button size="small" color="primary" onClick={addDefect}>
                + Add another defect
              </Button>
            </Section>

            <Divider sx={{ mb: 3 }} />

            {/* ----- Measurement parameters ----- */}
            <Section
              title="Part Parameters"
              subtitle="Add each dimension this part is measured on. The parameter name must match what the measurement step emits. The calibration factor scales the raw measurement before it is compared against the tolerances — leave it blank for no correction."
            >
              {dimensions.map((d, i) => (
                <Box
                  key={i}
                  sx={{
                    display: "grid",
                    gridTemplateColumns: {
                      xs: "1fr",
                      md: "auto 1.4fr 1fr 1fr 1fr 0.8fr 0.9fr auto",
                    },
                    gap: 1,
                    mb: 1,
                    alignItems: "center",
                  }}
                >
                  <Typography
                    variant="caption"
                    sx={{ color: "text.secondary", minWidth: 30 }}
                  >
                    p{i + 1}
                  </Typography>
                  <TextField
                    label="Parameter name"
                    value={d.param_name}
                    sx={inputSx}
                    onChange={(e) => updateDimension(i, "param_name", e.target.value)}
                  />
                  <TextField
                    label="Nominal"
                    value={d.nominal}
                    sx={inputSx}
                    inputProps={{ inputMode: "decimal" }}
                    onChange={(e) =>
                      numeric(e.target.value) &&
                      updateDimension(i, "nominal", e.target.value)
                    }
                  />
                  <TextField
                    label="Lower tolerance"
                    value={d.lower_limit}
                    sx={inputSx}
                    inputProps={{ inputMode: "decimal" }}
                    onChange={(e) =>
                      numeric(e.target.value) &&
                      updateDimension(i, "lower_limit", e.target.value)
                    }
                  />
                  <TextField
                    label="Upper tolerance"
                    value={d.upper_limit}
                    sx={inputSx}
                    inputProps={{ inputMode: "decimal" }}
                    onChange={(e) =>
                      numeric(e.target.value) &&
                      updateDimension(i, "upper_limit", e.target.value)
                    }
                  />
                  <TextField
                    select
                    label="Unit"
                    value={d.unit}
                    sx={inputSx}
                    onChange={(e) => updateDimension(i, "unit", e.target.value)}
                  >
                    {UNIT_OPTIONS.map((u) => (
                      <MenuItem key={u || "none"} value={u}>
                        {u || "— none —"}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    label="Cal. factor"
                    value={d.calibration_factor}
                    placeholder="1.000"
                    sx={inputSx}
                    inputProps={{ inputMode: "decimal" }}
                    onChange={(e) =>
                      nonNegative(e.target.value) &&
                      updateDimension(i, "calibration_factor", e.target.value)
                    }
                  />
                  {i > 0 && (
                    <IconButton size="small" onClick={() => removeDimension(i)}>
                      ✕
                    </IconButton>
                  )}
                </Box>
              ))}
              <Button size="small" color="primary" onClick={addDimension}>
                + Add another parameter
              </Button>
            </Section>

            <Divider sx={{ mb: 3 }} />

            <Section title="Part Image">
              <Button
                variant="outlined"
                color="primary"
                component="label"
                disabled={!canEdit}
              >
                Upload Image (PNG / JPEG)
                <input
                  id="single-image-input"
                  type="file"
                  accept="image/png,image/jpeg"
                  hidden
                  disabled={!canEdit}
                  onChange={(e) => setImageFile(e.target.files?.[0] || null)}
                />
              </Button>
              {imageFile && (
                <Box sx={{ mt: 1.5 }}>
                  <img
                    src={imagePreview}
                    alt="preview"
                    style={{
                      width: 110,
                      height: 110,
                      objectFit: "cover",
                      borderRadius: 8,
                      border: "1px solid #E5E7EB",
                    }}
                  />
                </Box>
              )}
            </Section>

            <Box
              sx={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 2,
                pt: 1,
                borderTop: 1,
                borderColor: "divider",
              }}
            >
              <Button
                variant="outlined"
                color="secondary"
                onClick={resetForm}
                disabled={!canEdit}
                sx={{ mt: 2 }}
              >
                Reset
              </Button>
              <Button
                variant="contained"
                color="primary"
                size="large"
                onClick={handleAddPart}
                disabled={!canEdit || submitting}
                sx={{ mt: 2, px: 4, ...persistentPrimary(theme) }}
              >
                {submitting ? "Saving..." : "Submit Part"}
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