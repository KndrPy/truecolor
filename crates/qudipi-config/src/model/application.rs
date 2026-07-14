use qudipi_domain::{ProjectId, ResearchPackId, StudyId};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ApplicationConfig {
    pub id: ProjectId,
    pub phase: u8,
    pub study: StudyId,
    pub research_pack: ResearchPackId,
    pub single_config_authority: bool,
}
