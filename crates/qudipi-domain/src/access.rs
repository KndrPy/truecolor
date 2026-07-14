use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AccessClass {
    Public,
    ProjectPrivate,
    LocallyGoverned,
    Restricted,
    DerivedSummary,
    ExportProhibited,
}

impl AccessClass {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Public => "public",
            Self::ProjectPrivate => "project_private",
            Self::LocallyGoverned => "locally_governed",
            Self::Restricted => "restricted",
            Self::DerivedSummary => "derived_summary",
            Self::ExportProhibited => "export_prohibited",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::AccessClass;

    #[test]
    fn access_classes_have_canonical_strings() {
        assert_eq!(AccessClass::Public.as_str(), "public");
        assert_eq!(AccessClass::ProjectPrivate.as_str(), "project_private");
        assert_eq!(AccessClass::LocallyGoverned.as_str(), "locally_governed");
        assert_eq!(AccessClass::Restricted.as_str(), "restricted");
        assert_eq!(AccessClass::DerivedSummary.as_str(), "derived_summary");
        assert_eq!(AccessClass::ExportProhibited.as_str(), "export_prohibited");
    }
}
