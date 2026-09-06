import { Tabs, Tab } from "@mui/material";

// Only rendered when stations don't fit on one page (see InspectionPage.jsx's
// PAGE_CAPACITY) -- tab switch is pure client-side state, no refetch.
const PageTabs = ({ pageCount, activePage, onChange }) => {
  if (pageCount <= 1) return null;
  return (
    <Tabs
      value={activePage}
      onChange={(_e, value) => onChange(value)}
      sx={{ mb: 2, minHeight: 36 }}
      textColor="primary"
      indicatorColor="primary"
    >
      {Array.from({ length: pageCount }, (_, i) => (
        <Tab key={i} label={`Page ${i + 1}`} sx={{ minHeight: 36, fontWeight: 600 }} />
      ))}
    </Tabs>
  );
};

export default PageTabs;
