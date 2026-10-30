/**
 * Draws one region of a photograph as a mesh in WebGL, so parts of the face
 * can stretch and move like skin. Shared by the talking mouth and the
 * blinking eyelids.
 */
type Region = { x: number; y: number; width: number; height: number };
export type Mesh = {
  /** Photo coordinates (0–100) of each vertex, as x, y pairs. */
  source: Float32Array;
  /** How much each vertex darkens with `shade` (for the inner lip). */
  shade: Float32Array;
  indices: Uint16Array;
};

const VERTEX = `
attribute vec2 a_src;
attribute vec2 a_pos;
attribute float a_shade;
uniform vec4 u_region;
varying vec2 v_src;
varying float v_shade;
void main() {
  vec2 p = (a_pos - u_region.xy) / u_region.zw;
  gl_Position = vec4(p.x * 2.0 - 1.0, 1.0 - p.y * 2.0, 0.0, 1.0);
  v_src = a_src;
  v_shade = a_shade;
}`;
const FRAGMENT = `
precision mediump float;
uniform sampler2D u_image;
// Same values as u_region; a separate name because uniforms shared between
// shaders must match precision, and the vertex shader's is highp.
uniform vec4 u_bounds;
uniform vec4 u_crop;
uniform float u_shade;
varying vec2 v_src;
varying float v_shade;
void main() {
  vec4 color = texture2D(u_image, (v_src - u_crop.xy) / u_crop.zw);
  // Moist inner lip: a little darker, slightly redder.
  color.rgb *= 1.0 - u_shade * v_shade * vec3(0.24, 0.33, 0.3);
  // Fade out at the edges of the region, where nothing moves, so the layer
  // meets the photo underneath without a seam.
  vec2 a = v_src - u_bounds.xy;
  vec2 b = u_bounds.xy + u_bounds.zw - v_src;
  float edge = min(min(a.x, a.y), min(b.x, b.y));
  gl_FragColor = color * smoothstep(0.0, 1.2, edge);
}`;

/** A regular grid over the region, rows given by `rowY(column x, t)`. */
export function gridMesh(
  region: Region,
  columns: number,
  bands: { rows: number; y: (x: number, t: number) => number; shade?: (x: number, y: number) => number }[],
): Mesh & { band: Uint8Array } {
  const source: number[] = [];
  const shade: number[] = [];
  const band: number[] = [];
  const indices: number[] = [];
  bands.forEach((b, index) => {
    const base = source.length / 2;
    for (let r = 0; r <= b.rows; r++)
      for (let c = 0; c <= columns; c++) {
        const x = region.x + (region.width * c) / columns;
        const y = b.y(x, r / b.rows);
        source.push(x, y);
        shade.push(b.shade ? b.shade(x, y) : 0);
        band.push(index);
      }
    for (let r = 0; r < b.rows; r++)
      for (let c = 0; c < columns; c++) {
        const a = base + r * (columns + 1) + c;
        const d = a + columns + 1;
        indices.push(a, d, a + 1, a + 1, d, d + 1);
      }
  });
  return {
    source: new Float32Array(source),
    shade: new Float32Array(shade),
    indices: new Uint16Array(indices),
    band: new Uint8Array(band),
  };
}

function compile(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type)!;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  return shader;
}

/**
 * Prepares `canvas` to draw `region` of `image` through `mesh`. Returns a
 * draw function taking the moved vertex positions, or null without WebGL.
 */
export function createFaceWarp(
  canvas: HTMLCanvasElement,
  image: HTMLImageElement,
  region: Region,
  mesh: Mesh,
) {
  const gl = canvas.getContext("webgl", {
    premultipliedAlpha: true,
    antialias: true,
    alpha: true,
  });
  if (!gl) return null;
  const program = gl.createProgram()!;
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  gl.useProgram(program);

  const attribute = (data: Float32Array, name: string, size: number, usage: number) => {
    const handle = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, handle);
    gl.bufferData(gl.ARRAY_BUFFER, data, usage);
    const location = gl.getAttribLocation(program, name);
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, size, gl.FLOAT, false, 0, 0);
    return handle;
  };
  attribute(mesh.source, "a_src", 2, gl.STATIC_DRAW);
  attribute(mesh.shade, "a_shade", 1, gl.STATIC_DRAW);
  const positions = attribute(new Float32Array(mesh.source), "a_pos", 2, gl.DYNAMIC_DRAW);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, mesh.indices, gl.STATIC_DRAW);

  // Only this region is needed. Resampled to a power-of-two square it can
  // have mipmaps, so it stays smooth at any size, like the photo itself.
  const crop = {
    x: region.x - 1,
    y: region.y - 1,
    width: region.width + 2,
    height: region.height + 2,
  };
  const square = document.createElement("canvas");
  square.width = square.height = 1024;
  const scale = image.naturalWidth / 100;
  square
    .getContext("2d")!
    .drawImage(
      image,
      crop.x * scale,
      crop.y * scale,
      crop.width * scale,
      crop.height * scale,
      0,
      0,
      1024,
      1024,
    );
  gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, square);
  gl.generateMipmap(gl.TEXTURE_2D);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const uniform = (name: string) => gl.getUniformLocation(program, name);
  gl.uniform4f(uniform("u_region"), region.x, region.y, region.width, region.height);
  gl.uniform4f(uniform("u_bounds"), region.x, region.y, region.width, region.height);
  gl.uniform4f(uniform("u_crop"), crop.x, crop.y, crop.width, crop.height);
  const shade = uniform("u_shade");

  return (moved: Float32Array, shadeAmount = 0) => {
    gl.bindBuffer(gl.ARRAY_BUFFER, positions);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, moved);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform1f(shade, shadeAmount);
    gl.drawElements(gl.TRIANGLES, mesh.indices.length, gl.UNSIGNED_SHORT, 0);
  };
}

/** Loads the photograph once for every face layer on the page. */
const images = new Map<string, Promise<HTMLImageElement>>();
export function loadImage(src: string) {
  let image = images.get(src);
  if (!image) {
    const element = new Image();
    element.decoding = "async";
    element.src = src;
    image = element.decode().then(() => element);
    images.set(src, image);
  }
  return image;
}

/**
 * Keeps a canvas box's pixel size matched to its size on screen, including
 * CSS scaling (which never fires a resize). `check` re-measures at most a
 * few times a second; call it before drawing.
 */
export function watchSize(
  box: HTMLElement,
  canvases: HTMLCanvasElement[],
  onResize: () => void,
) {
  let measured = 0;
  const resize = () => {
    measured = performance.now();
    const rect = box.getBoundingClientRect();
    const scale = Math.min(window.devicePixelRatio || 1, 2.5);
    const width = Math.max(8, Math.round(rect.width * scale));
    const height = Math.max(8, Math.round(rect.height * scale));
    let changed = false;
    for (const canvas of canvases)
      if (Math.abs(canvas.width - width) > 2 || Math.abs(canvas.height - height) > 2) {
        canvas.width = width;
        canvas.height = height;
        changed = true;
      }
    return changed;
  };
  const observer = new ResizeObserver(() => {
    resize();
    onResize();
  });
  observer.observe(box);
  resize();
  return {
    stop: () => observer.disconnect(),
    check: () => (performance.now() - measured > 250 ? resize() : false),
  };
}
