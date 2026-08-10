// BAML is used as a parser-only structural alignment layer. Runtime provider
// calls continue to flow through ModelGateway, so third-party routing and
// credentials stay under the application's existing authority boundary.
client ParserOnly {
  provider openai-generic
  options {
    model "parser-only"
    base_url "http://127.0.0.1"
    api_key "not-used"
  }
}

class CausalCycleWire {
  obstacle string
  effort string
  result string
  state_change string
}

function ParseCausalCycles(raw_cycle_array: string) -> CausalCycleWire[] {
  client ParserOnly
  prompt #"
    Parse the supplied unique causal-cycle array. The object field names may
    differ, but preserve each complete obstacle -> effort -> result ->
    state-change cycle and its original order.

    {{ raw_cycle_array }}
  "#
}
