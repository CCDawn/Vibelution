//! Provider usage normalization (OpenAI + Anthropic-native + relays).
//!
//! Contract: cache hit rate is **cache_read / total_input**.
//! For Anthropic-native payloads, `input_tokens` is the non-cached tail only:
//! `total_input = cache_read + cache_creation + input_tail`.

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct NormalizedUsage {
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub total_tokens: u64,
    pub cached_input_tokens: u64,
    pub cache_read_input_tokens: u64,
    pub cache_creation_input_tokens: u64,
    pub uncached_input_tokens: u64,
    pub cache_hit_rate: f64,
    pub engine: String,
}

fn read_u64(v: &Value, keys: &[&str]) -> u64 {
    for key in keys {
        if let Some(n) = v.get(*key) {
            if let Some(i) = n.as_u64() {
                return i;
            }
            if let Some(i) = n.as_i64() {
                return i.max(0) as u64;
            }
            if let Some(f) = n.as_f64() {
                if f.is_finite() && f >= 0.0 {
                    return f.floor() as u64;
                }
            }
        }
    }
    0
}

fn nested_u64(v: &Value, object_keys: &[&str], field_keys: &[&str]) -> u64 {
    for ok in object_keys {
        if let Some(obj) = v.get(*ok) {
            let n = read_u64(obj, field_keys);
            if n > 0 {
                return n;
            }
        }
    }
    0
}

/// Normalize a provider usage JSON object.
pub fn normalize_usage(raw: &Value, engine: &str) -> NormalizedUsage {
    let prompt_tokens = read_u64(raw, &["prompt_tokens", "promptTokens"]);
    let input_field = read_u64(raw, &["input_tokens", "inputTokens", "input_token_count"]);
    let input_from_meta = nested_u64(
        raw,
        &["usage_metadata", "usageMetadata", "input_token_details", "input_tokens_details"],
        &["prompt_tokens", "input_tokens", "input_token_count", "promptTokens", "inputTokens"],
    );

    let cache_read = [
        read_u64(
            raw,
            &[
                "cache_read_input_tokens",
                "cacheReadInputTokens",
                "cached_input_tokens",
                "cachedInputTokens",
                "cached_tokens",
                "prompt_cache_hit_tokens",
            ],
        ),
        nested_u64(
            raw,
            &["prompt_tokens_details", "promptTokensDetails", "input_token_details", "input_tokens_details", "usage_metadata"],
            &["cached_tokens", "cached_input_tokens", "cache_read_input_tokens", "cachedTokens"],
        ),
    ]
    .into_iter()
    .max()
    .unwrap_or(0);

    let cache_creation = [
        read_u64(
            raw,
            &[
                "cache_creation_input_tokens",
                "cacheCreationInputTokens",
                "cache_write_input_tokens",
                "prompt_cache_creation_tokens",
            ],
        ),
        nested_u64(
            raw,
            &["prompt_tokens_details", "promptTokensDetails", "usage_metadata"],
            &["cache_creation_input_tokens", "cache_write_input_tokens", "prompt_cache_creation_tokens"],
        ),
    ]
    .into_iter()
    .max()
    .unwrap_or(0);

    let output_tokens = [
        read_u64(raw, &["completion_tokens", "output_tokens", "outputTokens", "output_token_count"]),
        nested_u64(
            raw,
            &["usage_metadata", "completion_tokens_details"],
            &["completion_tokens", "output_tokens"],
        ),
    ]
    .into_iter()
    .max()
    .unwrap_or(0);

    let mut total_tokens = read_u64(raw, &["total_tokens", "totalTokens"]);

    // Heuristic: Anthropic-native when read/create present and declared input looks like a tail
    // (smaller than read, or prompt_tokens missing while cache fields dominate).
    let declared_input = prompt_tokens.max(input_field).max(input_from_meta);
    let anthropic_sum = cache_read.saturating_add(cache_creation).saturating_add(input_field);
    // Anthropic-native: input_tokens is the unpaid tail and is smaller than cache read/write.
    // OpenAI-compatible: input_tokens is already the full prompt (read+create typically ≤ input).
    let looks_anthropic_native = (cache_read > 0 || cache_creation > 0)
        && input_field > 0
        && prompt_tokens == 0
        && (cache_read > input_field || cache_creation > input_field);

    let input_tokens = if looks_anthropic_native {
        anthropic_sum
    } else if prompt_tokens > 0 {
        // OpenAI / relays: prompt_tokens is full prompt; prefer it over a smaller input_tokens tail.
        prompt_tokens.max(input_field).max(input_from_meta)
    } else {
        // input_tokens already represents the provider total (OpenAI-compatible).
        declared_input
    };

    let cached = if input_tokens > 0 {
        cache_read.min(input_tokens)
    } else {
        cache_read
    };
    let creation = if input_tokens > 0 {
        cache_creation.min(input_tokens)
    } else {
        cache_creation
    };
    let uncached = input_tokens.saturating_sub(cached);
    let hit = if input_tokens > 0 {
        (cached as f64) / (input_tokens as f64)
    } else {
        0.0
    };

    if total_tokens == 0 {
        total_tokens = input_tokens + output_tokens;
    }

    NormalizedUsage {
        input_tokens,
        output_tokens,
        total_tokens,
        cached_input_tokens: cached,
        cache_read_input_tokens: cached,
        cache_creation_input_tokens: creation,
        uncached_input_tokens: uncached,
        cache_hit_rate: (hit * 10000.0).round() / 10000.0,
        engine: engine.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn openai_hit_rate() {
        let raw = json!({
            "prompt_tokens": 10000,
            "completion_tokens": 100,
            "total_tokens": 10100,
            "prompt_tokens_details": { "cached_tokens": 9000 }
        });
        let n = normalize_usage(&raw, "rust");
        assert_eq!(n.input_tokens, 10000);
        assert_eq!(n.cached_input_tokens, 9000);
        assert!((n.cache_hit_rate - 0.9).abs() < 1e-9);
        assert_eq!(n.uncached_input_tokens, 1000);
    }

    #[test]
    fn anthropic_native_does_not_cap_read_to_tail() {
        let raw = json!({
            "input_tokens": 200,
            "output_tokens": 80,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 4000
        });
        let n = normalize_usage(&raw, "rust");
        assert_eq!(n.input_tokens, 4700);
        assert_eq!(n.cached_input_tokens, 4000);
        assert_eq!(n.cache_creation_input_tokens, 500);
        assert_eq!(n.uncached_input_tokens, 700);
        assert!((n.cache_hit_rate - 0.8511).abs() < 1e-6);
    }

    #[test]
    fn openai_style_with_cache_fields_keeps_input_as_total() {
        // Existing Python test contract shape: input_tokens already full total.
        let raw = json!({
            "input_tokens": 200,
            "output_tokens": 10,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 40
        });
        // Without prompt_tokens, and read < input → not anthropic-native tail pattern.
        let n = normalize_usage(&raw, "rust");
        assert_eq!(n.input_tokens, 200);
        assert_eq!(n.cached_input_tokens, 80);
        assert!((n.cache_hit_rate - 0.4).abs() < 1e-9);
    }
}
