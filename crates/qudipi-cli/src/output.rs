use anyhow::Result;
use serde::Serialize;

pub fn print_json<T>(value: &T) -> Result<()>
where
    T: Serialize + ?Sized,
{
    println!("{}", serde_json::to_string(value)?);
    Ok(())
}
