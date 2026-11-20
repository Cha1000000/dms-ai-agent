#version 450

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float widthPx;
    float heightPx;
    float radiusPx;
    float strokePx;
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
    float innerCut = smoothstep(-ubuf.strokePx - hw, -ubuf.strokePx + hw, d);
    float ring = outerCov * innerCut;

    float t = clamp(dot(qt_TexCoord0 * size, size) / max(dot(size, size), 1.0), 0.0, 1.0);
    float gAlpha;
    if (t < 0.25) {
        gAlpha = mix(0.75, 0.18, t / 0.25);
    } else if (t < 0.60) {
        gAlpha = mix(0.18, 0.04, (t - 0.25) / 0.35);
    } else {
        gAlpha = mix(0.04, 0.35, (t - 0.60) / 0.40);
    }

    float a = gAlpha * ring * ubuf.qt_Opacity;
    fragColor = vec4(a, a, a, a);
}
