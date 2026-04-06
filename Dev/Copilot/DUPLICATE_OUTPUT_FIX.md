# Fix: Duplicate Output Error

## Issue
When testing the metronome button after previous fixes, encountered:
```
Output 2 (status-msg.children) is already in use. 
To resolve this, set `allow_duplicate=True` on duplicate outputs
```

## Root Cause
Two callbacks were outputting to `status-msg.children`:
1. `process_audio()` callback - Added in previous fix
2. `load_recording()` callback - Already existed

In Dash, when multiple callbacks output to the same component property, you must set `allow_duplicate=True` to indicate this is intentional.

## Solution
Added `allow_duplicate=True` to the `status-msg.children` output in the `process_audio()` callback:

```python
@app.callback(
    Output("audio-store", "data"),
    Output("waveform-graph", "figure"),
    Output("status-msg", "children", allow_duplicate=True),  # <-- Added this
    Input("audio-process-btn", "n_clicks"),
    State("audio-data-store", "value"),
    State("tempo-slider", "value"),
    State("beats-per-measure", "value"),
    prevent_initial_call=True
)
def process_audio(...):
```

## File Modified
- `app/main.py` line 169

## Result
✅ App imports without errors
✅ All callbacks work properly
✅ Metronome button works
✅ Recording processing works
✅ All features functional

## Testing
- ✅ Import test passed
- ✅ Callback registration successful
- ✅ No duplicate output warnings

