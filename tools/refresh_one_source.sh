#!/usr/bin/env bash
set -uo pipefail

SOURCE="${1:?source required}"
HOURS="${2:-48}"
ROOT="${GITHUB_WORKSPACE:-$(pwd)}"
UPSTREAM="$ROOT/vendor/iptv-org-epg"
mkdir -p "$ROOT/output/source-build" "$ROOT/output/final" "$ROOT/output/morocco" "$ROOT/reports" "$ROOT/data"

empty_xml() {
  printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?><tv></tv>' > "$1"
}

has_programmes() {
  grep -q '<programme ' "$1" 2>/dev/null
}

grab_upstream() {
  key="$1"; channels="$2"; output="$3"; delay="${4:-}"
  set +e
  cd "$UPSTREAM"
  cmd=(npm run grab -- "--channels=$channels" "--output=$output" --days=3 --maxConnections=1 --timeout=20000)
  [ -n "$delay" ] && cmd+=("--delay=$delay")
  timeout --signal=TERM --kill-after=30s 900s "${cmd[@]}"
  rc=$?
  cd "$ROOT"
  [ -s "$output" ] || empty_xml "$output"
  return $rc
}

pack_source() {
  key="$1"; input="$2"; catalogue="${3:-}"
  args=(python tools/source_feed_pack.py --input "$input" --output-gz "output/final/$key.xml.gz" --output-txt "output/final/$key.txt" --stats "output/final/$key.json" --label "$key" --window-hours "$HOURS")
  [ -n "$catalogue" ] && [ -s "$catalogue" ] && args+=(--catalogue "$catalogue")
  "${args[@]}"
}

case "$SOURCE" in
  bein)
    grab_upstream bein "$ROOT/output/source-build/bein.channels.xml" "$ROOT/output/source-build/bein.raw.xml" "" || true
    grab_upstream bein-hybrid "$ROOT/output/source-build/bein_hybrid_en.channels.xml" "$ROOT/output/source-build/bein.hybrid.en.raw.xml" "500" || true
    pack_source bein output/source-build/bein.raw.xml output/source-build/bein.channels.xml || true
    if [ -s output/final/bein.xml.gz ]; then
      python tools/bein_arabize.py --input output/final/bein.xml.gz --output output/final/bein.ar.xml.gz --cache data/bein_translation_cache.json --report reports/bein-translation.json || true
      [ -s output/final/bein.ar.xml.gz ] && mv output/final/bein.ar.xml.gz output/final/bein.xml.gz
    fi
    if [ -n "${OPENAI_API_KEY:-}${GEMINI_API_KEY:-}" ] && [ -s output/final/bein.xml.gz ]; then
      python tools/bein_ai_refine.py --input output/final/bein.xml.gz --output output/final/bein.ai.xml.gz --cache data/bein_ai_cache.json --report reports/bein-ai-refine.json || true
      [ -s output/final/bein.ai.xml.gz ] && mv output/final/bein.ai.xml.gz output/final/bein.xml.gz
    fi
    if [ -s output/final/bein.xml.gz ] && has_programmes output/source-build/bein.hybrid.en.raw.xml; then
      python tools/bein_hybrid.py --input output/final/bein.xml.gz --english output/source-build/bein.hybrid.en.raw.xml --policy config/bein-language-policy.json --cache data/bein_hybrid_translation_cache.json --output output/final/bein.hybrid.xml.gz --report reports/bein-hybrid.json || true
      [ -s output/final/bein.hybrid.xml.gz ] && mv output/final/bein.hybrid.xml.gz output/final/bein.xml.gz
    fi
    ;;

  osn)
    grab_upstream osn "$ROOT/output/source-build/osn.channels.xml" "$ROOT/output/source-build/osn.raw.xml" "" || true
    grab_upstream osn-en "$ROOT/output/source-build/osn_en.channels.xml" "$ROOT/output/source-build/osn.en.raw.xml" "" || true
    if has_programmes output/source-build/osn.raw.xml && has_programmes output/source-build/osn.en.raw.xml; then
      python tools/osn_hybrid.py --arabic output/source-build/osn.raw.xml --english output/source-build/osn.en.raw.xml --policy config/osn-language-policy.json --mode hybrid --output output/source-build/osn.hybrid.raw.xml --report reports/osn-hybrid.json || true
      [ -s output/source-build/osn.hybrid.raw.xml ] && mv output/source-build/osn.hybrid.raw.xml output/source-build/osn.raw.xml
    fi
    pack_source osn output/source-build/osn.raw.xml output/source-build/osn.channels.xml || true
    ;;

  shahid)
    grab_upstream shahid "$ROOT/output/source-build/shahid.channels.xml" "$ROOT/output/source-build/shahid.raw.xml" "" || true
    pack_source shahid output/source-build/shahid.raw.xml output/source-build/shahid.channels.xml || true
    ;;

  elcinema)
    grab_upstream elcinema "$ROOT/output/source-build/elcinema.channels.xml" "$ROOT/output/source-build/elcinema.raw.xml" "1000" || true
    python tools/elcinema_hybrid.py catalogue --fallback-catalogue output/source-build/elcinema_fallback.channels.xml --policy config/elcinema-language-policy.json --output output/source-build/elcinema_hybrid_en.channels.xml || true

    python tools/source_gap_retry.py build --catalogue output/source-build/elcinema.channels.xml --fallback-catalogue output/source-build/elcinema_fallback.channels.xml --raw output/source-build/elcinema.raw.xml --output output/source-build/elcinema.retry.channels.xml || true
    if grep -q '<channel ' output/source-build/elcinema.retry.channels.xml 2>/dev/null; then
      grab_upstream elcinema-retry "$ROOT/output/source-build/elcinema.retry.channels.xml" "$ROOT/output/source-build/elcinema.retry.raw.xml" "1000" || true
      if has_programmes output/source-build/elcinema.retry.raw.xml; then
        python tools/source_gap_retry.py merge --primary output/source-build/elcinema.raw.xml --retry output/source-build/elcinema.retry.raw.xml --output output/source-build/elcinema.merged.xml || true
        [ -s output/source-build/elcinema.merged.xml ] && mv output/source-build/elcinema.merged.xml output/source-build/elcinema.raw.xml
      fi
    fi

    grab_upstream elcinema-en "$ROOT/output/source-build/elcinema_hybrid_en.channels.xml" "$ROOT/output/source-build/elcinema.hybrid.en.raw.xml" "1000" || true
    if has_programmes output/source-build/elcinema.raw.xml && has_programmes output/source-build/elcinema.hybrid.en.raw.xml; then
      python tools/elcinema_hybrid.py merge --arabic output/source-build/elcinema.raw.xml --english output/source-build/elcinema.hybrid.en.raw.xml --policy config/elcinema-language-policy.json --cache data/elcinema_translation_cache.json --output output/source-build/elcinema.hybrid.raw.xml --report reports/elcinema-hybrid.json || true
      [ -s output/source-build/elcinema.hybrid.raw.xml ] && mv output/source-build/elcinema.hybrid.raw.xml output/source-build/elcinema.raw.xml
    fi
    pack_source elcinema output/source-build/elcinema.raw.xml output/source-build/elcinema.channels.xml || true
    ;;

  morocco)
    if [ -s feeds/morocco.xml.gz ]; then
      python tools/morocco_epg.py --output-dir output/morocco --days 3 --previous feeds/morocco.xml.gz || true
    else
      python tools/morocco_epg.py --output-dir output/morocco --days 3 || true
    fi
    if [ -s output/morocco/morocco.xml.gz ]; then
      pack_source morocco output/morocco/morocco.xml.gz "" || true
    fi
    ;;

  rotana)
    python tools/rotana_source.py --output output/source-build/rotana.raw.xml --report reports/rotana-scrape.json --window-hours "$HOURS" || true
    [ -s output/source-build/rotana.raw.xml ] || empty_xml output/source-build/rotana.raw.xml
    pack_source rotana output/source-build/rotana.raw.xml "" || true
    ;;

  sport24)
    python tools/sport24_source.py --output output/source-build/sport24.raw.xml --report reports/sport24-scrape.json --window-hours "$HOURS" || true
    [ -s output/source-build/sport24.raw.xml ] || empty_xml output/source-build/sport24.raw.xml
    pack_source sport24 output/source-build/sport24.raw.xml "" || true
    ;;

  dubaiplus)
    python tools/dubaiplus_api_source.py --output output/source-build/dubaiplus.raw.xml --report reports/dubaiplus-scrape.json --hours "$HOURS" || true
    [ -s output/source-build/dubaiplus.raw.xml ] || empty_xml output/source-build/dubaiplus.raw.xml
    pack_source dubaiplus output/source-build/dubaiplus.raw.xml "" || true
    ;;

  stctv)
    # STC is deliberately isolated: it can be slow without delaying any other source.
    python tools/stctv_source.py --output output/source-build/stctv.raw.xml --report reports/stctv-scrape.json --id-index feeds/mena.txt --window-hours "$HOURS" --delay 0.2 --max-channels 0 --profile all || true
    [ -s output/source-build/stctv.raw.xml ] || empty_xml output/source-build/stctv.raw.xml
    pack_source stctv output/source-build/stctv.raw.xml "" || true
    ;;

  starzplay)
    for lang in ar en; do
      python tools/starzplay_source.py --lang "$lang" --output "output/source-build/starzplay.$lang.raw.xml" --report "reports/starzplay-$lang-scrape.json" --id-index feeds/mena.txt --hours "$HOURS" || true
      [ -s "output/source-build/starzplay.$lang.raw.xml" ] || empty_xml "output/source-build/starzplay.$lang.raw.xml"
    done
    if has_programmes output/source-build/starzplay.ar.raw.xml; then
      cp output/source-build/starzplay.ar.raw.xml output/source-build/starzplay.raw.xml
      if has_programmes output/source-build/starzplay.en.raw.xml; then
        python tools/starzplay_hybrid.py --arabic output/source-build/starzplay.ar.raw.xml --english output/source-build/starzplay.en.raw.xml --policy config/starzplay-language-policy.json --output output/source-build/starzplay.hybrid.raw.xml --report reports/starzplay-hybrid.json || true
        [ -s output/source-build/starzplay.hybrid.raw.xml ] && mv output/source-build/starzplay.hybrid.raw.xml output/source-build/starzplay.raw.xml
      fi
      pack_source starzplay output/source-build/starzplay.raw.xml "" || true
      printf '%s\n' '{"mode":"direct-starzplay","fallback":false}' > reports/starzplay-source-mode.json
    else
      echo "STARZPLAY direct endpoint unavailable; using official STC metadata for STARZPLAY Sports only."
      python tools/stctv_source.py \
        --output output/source-build/starzplay.raw.xml \
        --report reports/starzplay-fallback-stctv.json \
        --id-index feeds/mena.txt \
        --window-hours "$HOURS" \
        --delay 0.2 \
        --max-channels 0 \
        --profile starzplay-sports || true
      if has_programmes output/source-build/starzplay.raw.xml; then
        pack_source starzplay output/source-build/starzplay.raw.xml "" || true
        printf '%s\n' '{"mode":"stctv-public-metadata-fallback","fallback":true,"scope":"STARZPLAY Sports 1-3"}' > reports/starzplay-source-mode.json
      else
        echo "STARZPLAY fallback also unavailable; LKG will be preserved."
      fi
    fi
    ;;

  gobx)
    if [ -f tools/gobx_source.py ]; then
      python tools/gobx_source.py --output output/source-build/gobx.raw.xml --report reports/gobx-scrape.json --hours "$HOURS" || true
      if [ -s output/source-build/gobx.raw.xml ] && has_programmes output/source-build/gobx.raw.xml; then
        pack_source gobx output/source-build/gobx.raw.xml "" || true
      else
        echo "GOBX public EPG metadata unavailable; LKG will be preserved."
      fi
    else
      python tools/gobx_probe.py || true
      echo "GOBX source adapter not available yet; LKG will be preserved."
    fi
    ;;

  *)
    echo "Unsupported source: $SOURCE" >&2
    exit 2
    ;;
esac

if [ -s "output/final/$SOURCE.xml.gz" ]; then
  python tools/validate_48h.py "output/final/$SOURCE.xml.gz" --hours "$HOURS" --max-gap-minutes 90 --report "reports/$SOURCE-48h-audit.json" || true
fi

python tools/publish_lkg.py --source "$SOURCE" --report "reports/$SOURCE-publish-lkg.json" || true
echo "SOURCE_REFRESH_DONE source=$SOURCE hours=$HOURS"
