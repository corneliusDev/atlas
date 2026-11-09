/**
 * Sigma node program for ghost nodes (unresolved [[wikilinks]]): a dashed ring with a faint
 * fill, so they read as "a note that does not exist yet", the way Obsidian shows them.
 * It reuses NodeCircleProgram's vertex shader and attributes and swaps the fragment shader.
 */
import { NodeCircleProgram } from "sigma/rendering";
import type { Attributes } from "graphology-types";

const FRAGMENT_SHADER_SOURCE = /* glsl */ `
precision highp float;

varying vec4 v_color;
varying vec2 v_diffVector;
varying float v_radius;

uniform float u_correctionRatio;

const vec4 transparent = vec4(0.0, 0.0, 0.0, 0.0);
const float PI = 3.14159265359;
const float DASHES = 10.0;

void main(void) {
  float dist = length(v_diffVector);

  #ifdef PICKING_MODE
  // Pick on the whole disc so hovering the hollow centre still works.
  if (dist > v_radius)
    gl_FragColor = transparent;
  else
    gl_FragColor = v_color;
  #else
  float ring = u_correctionRatio * 3.0;
  float aa = u_correctionRatio * 1.5;
  if (dist > v_radius) {
    gl_FragColor = transparent;
  } else if (dist < v_radius - ring) {
    // Colours are premultiplied, so scale every channel for a translucent fill.
    gl_FragColor = v_color * 0.16;
  } else {
    float angle = atan(v_diffVector.y, v_diffVector.x);
    float on = step(0.45, fract(angle / (2.0 * PI) * DASHES));
    float edge = clamp((v_radius - dist) / aa, 0.0, 1.0);
    gl_FragColor = mix(v_color * 0.16, v_color, on) * edge;
  }
  #endif
}
`;

export class NodeDashedProgram<
  N extends Attributes = Attributes,
  E extends Attributes = Attributes,
  G extends Attributes = Attributes,
> extends NodeCircleProgram<N, E, G> {
  getDefinition() {
    return { ...super.getDefinition(), FRAGMENT_SHADER_SOURCE };
  }
}
