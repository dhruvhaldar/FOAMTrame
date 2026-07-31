# FOAMTrame_v2

A browser-based Python application for inspecting and slicing VTK surface and
volume datasets.

## Features

- Reads `.vtu`, `.vtp`, legacy `.vtk`, `.vti`, `.vtr`, `.vts`, `.ply`, `.stl`,
  and `.obj`.
- Slices a dataset along the X, Y, or Z axis.
- Clips either side of a plane.
- Colours results by scalar point or cell arrays.
- Shows the source dataset as adjustable translucent context.
- Uses Trame's server-side VTK rendering, so VTK processing remains in Python.

For surface meshes, **Slice** displays the plane/mesh intersection curve. For
volume meshes, it displays the cut surface. **Clip** works for both.

## Install

Python 3.10 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

```bash
.\venv\Scripts\python.exe app.py
```

Then open the URL printed in the terminal (normally
`http://localhost:8087`).

You can optionally load a server-local file at startup:

```bash
.\venv\Scripts\python.exe app.py --data /path/to/model.vtu
```

## Notes

- Browser upload is convenient for moderate-sized files. For very large
  datasets, use `--data` to avoid transferring the file through the browser.
- Only scalar (single-component) point and cell arrays appear in **Colour by**.
- XML parallel collection formats such as `.pvtu` are not included because
  their referenced piece files must be transferred together.
