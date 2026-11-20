#version 450

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float widthPx;
    float heightPx;
    float radiusPx;
    float thicknessPx;
    vec4 neon0;
    vec4 neon1;
    vec4 neon2;
    vec4 neon3;
} ubuf;

float sdRoundBox(vec2 p, vec2 hs, float r) {
    float rr = clamp(r, 0.0, min(hs.x, hs.y));
    vec2 q = abs(p) - hs + rr;
    return min(max(q.x, q.y), 0.0) + length(max(q, vec2(0.0))) - rr;
}

void main() {
    vec2 size = vec2(ubuf.widthPx, ubuf.heightPx);
    if (size.x < 2.0 || size.y < 2.0) {
        fragColor = vec4(0.0);
        return;
    }

    vec2 hs = size * 0.5;
    vec2 px = qt_TexCoord0 * size - hs;
    float d = sdRoundBox(px, hs, ubuf.radiusPx);

    float hw = max(fwidth(d) * 0.55, 1e-4);
    float outerCov = 1.0 - smoothstep(-hw, hw, d);
    float innerCut = smoothstep(-ubuf.thicknessPx - hw, -ubuf.thicknessPx + hw, d);
    float ring = outerCov * innerCut;

    float t = clamp(qt_TexCoord0.x, 0.0, 1.0);
    vec4 c;
    if (t < 0.35) {
        c = mix(ubuf.neon0, ubuf.neon1, t / 0.35);
    } else if (t < 0.70) {
        c = mix(ubuf.neon1, ubuf.neon2, (t - 0.35) / 0.35);
    } else {
        c = mix(ubuf.neon2, ubuf.neon3, (t - 0.70) / 0.30);
    }

    float a = c.a * ring * ubuf.qt_Opacity;
    fragColor = vec4(c.rgb * a, a);
}
