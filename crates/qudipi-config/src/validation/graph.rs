use crate::{ConfigError, StageConfig};
use std::collections::{BTreeMap, VecDeque};

pub(crate) fn validate(stages: &[StageConfig]) -> Result<(), ConfigError> {
    let mut indegree: BTreeMap<u8, usize> = stages.iter().map(|stage| (stage.id, 0)).collect();

    let mut adjacency: BTreeMap<u8, Vec<u8>> = BTreeMap::new();

    for stage in stages {
        for dependency in &stage.dependencies {
            *indegree
                .get_mut(&stage.id)
                .expect("stage identity validated before graph validation") += 1;

            adjacency.entry(*dependency).or_default().push(stage.id);
        }
    }

    let mut queue: VecDeque<u8> = indegree
        .iter()
        .filter_map(|(stage_id, degree)| (*degree == 0).then_some(*stage_id))
        .collect();

    let mut visited = 0usize;

    while let Some(current) = queue.pop_front() {
        visited += 1;

        if let Some(children) = adjacency.get(&current) {
            for child in children {
                let degree = indegree.get_mut(child).expect("child stage registered");

                *degree -= 1;

                if *degree == 0 {
                    queue.push_back(*child);
                }
            }
        }
    }

    if visited != stages.len() {
        return Err(ConfigError::Validation(
            "stage dependency graph contains a cycle".into(),
        ));
    }

    Ok(())
}
