// Some configuration properties for easy customization.

// Set how long to linger on a camera view, in seconds.
const static float GAZE_TIME = 7.0;
// Set how long to fade betwixt camera views, in seconds.
const static float FADE_TIME = 3.0;
// Set this for AA image quality. The shader takes like five seconds to compile if this
// is turned on, but it looks much nicer.
const static bool ANTIALIASING = true;
// Set this for light intensity. This might be a better parameter than DIM_EFFECT.
// A good dark value is 5; Nominal is 20. Crazygonuts is 200;
const static float LIGHT_INTENSITY = 5;
// Set this for screen emissive intensity.
// A good dark value is .25; Nominal is 1.
const static float SCREEN_INTENSITY = .25;
// Set this for sky intensity.
// A good dark value is .25; Nominal is 1.
const static float SKY_INTENSITY = .25;
// Set this 0-1 to darken the effect, for readability.
// Or set it to like 20 for garish antics.
// This is just an overall dimming. It might be better to play with
// LIGHT_INTENSITYH and SCREEN_INTENSITY.
const static float DIM_EFFECT = 1;

// We use what we're given.
Texture2D shaderTexture;
SamplerState samplerState;

// Terminal settings. This is what we're given.
cbuffer PixelShaderSettings {
    // The number of seconds since the pixel shader was enabled
    float Time;
    // UI Scale
    float Scale;
    // Resolution of the shaderTexture
    float2 Resolution;
    // Background color as rgba
    float4 Background;
};

/* Utility to do what % and fmod won't do: Give me a modulus function that
is consistent over positive and negative domains.
*/
float2 modul(float2 x, float2 y)
{
    return x - y * floor(x / y);
}

/* PRNG facilities. Make seemingly random floats with chunky fractional trig and
floating point goofiness.
*/

const static float randomMultiplier = 43758.5453123f;
const static float3 randomDotVector = float3(12.9898f, 78.233f, 133.223f);

// random float 0 to 1
float rand(uint seed)
{
    float f = frac(1.0f + sin(seed * randomDotVector.x) * randomMultiplier);
    return f;
}

// random float -1 to 1
float randsc(uint seed)
{
    return rand(seed) * 2 - 1;
}

// random float3 -1 to 1
float3 randv3(uint seed)
{
    return float3(randsc(seed), randsc(seed * 2 + 1), randsc(seed * 3 + 2));
}

#define TAU 6.28318530718

struct Ray
{
    float3 origin;
    float3 dir;
};

struct Camera
{
    Ray ray;
    float3 up;
    float3 left;
};

struct Light
{
    float3 p;
    float4 color;
};

struct Material
{
    float3 diffuseColor;
    float smoothness;
    float specularPower;
};

struct PlaneRect
{
    float3 p0;  // top-left corner
    float3 p1;  // top-right corner
    float3 p2;  // bottom-left corner
    float3 p3;  // bottom-right corner
    float3 normal;
    float d;
};

struct Sphere
{
    float3 p;
    float r;
};

/* Making the globals. This is setting up the world data. Some things in here
depend on time. We make materials, a planerect (the screen), sphere objects, 
lights, and cameras. The things we do for love.
*/

const static int NUM_MATERIALS = 2;
static Material materials[2];

void makeMaterials()
{
    // screen
    materials[0].diffuseColor = float3(.01, .01, .01);
    materials[0].smoothness = .25;
    materials[0].specularPower = 4;

    // mirror
    materials[1].diffuseColor = float3(.1, .1, .1);
    materials[1].smoothness = 1;
    materials[1].specularPower = 400;
}

static PlaneRect screen;

void makeScreen()
{
    float aspectRatio = Resolution.y / Resolution.x;

    screen.p0 = float3(-1, 0,  aspectRatio);
    screen.p1 = float3( 1, 0,  aspectRatio);
    screen.p2 = float3(-1, 0, -aspectRatio);
    screen.p3 = screen.p0 + (screen.p1 - screen.p0) + (screen.p2 - screen.p0);
    screen.normal = normalize(cross(screen.p1 - screen.p0, 
                                    screen.p2 - screen.p0));
    screen.d = - dot(screen.normal * screen.p0, float3(1, 1, 1));
}

const static int NUM_SPHERES = 8;
static Sphere spheres[8];

void makeSpheres()
{
    float m13 = cos(((Time / 13) % 1) * TAU) * .15;
    float m17 = cos(((Time / 17) % 1) * TAU) * .15;
    float m19 = cos(((Time / 19) % 1) * TAU) * .15;
    float m23 = cos(((Time / 23) % 1) * TAU) * .15;

    spheres[0].p = float3(-.6,          .05,        .35 + m13);
    spheres[0].r = .05;
    spheres[1].p = float3(-.75 + m13,   .03,        .16 + m17);
    spheres[1].r = .03;
    spheres[2].p = float3(.7 + m17,     .05,        .15 + m19);
    spheres[2].r = .05;
    spheres[3].p = float3(.35 + m17,    .02,        .06 + m13);
    spheres[3].r = .02;
    spheres[4].p = float3(-.3,          .1,         -.35 + m23);
    spheres[4].r = .1;
    spheres[5].p = float3(-.65 + m19,   .04,        -.16 + m17);
    spheres[5].r = .04;
    spheres[6].p = float3(.46 + m13,    .05,        -.35 + m19);
    spheres[6].r = .05;
    spheres[7].p = float3(.05,          .07,        -.05);
    spheres[7].r = .07;
}

const static int NUM_LIGHTS = 2;
static Light lights[2];

void makeLights()
{
    lights[0].p = float3(-3, 2, -2);
    lights[0].color = float4(float3(.75, .4, .1) * LIGHT_INTENSITY, 1);
    lights[1].p = float3(5, 2, -3);
    lights[1].color = float4(float3(1, 1, 1) * LIGHT_INTENSITY, 1);
}

static Camera cameras[2];

// Settings for camera gaze and fade times.
const static float HALFCYCLE_TIME = GAZE_TIME + FADE_TIME;
const static float CYCLE_TIME = HALFCYCLE_TIME * 2;

/* A suitable random camera position. seed is a uint for getting random float
values, and will be steady throughout a camera's cycle. Within the cycle, an
offset of small amount is allowed which depends on t, which must be set to run
from 0 to 1 over the course of the cycle.
*/ 
float3 randOrigin(uint seed, float t)
{
    return (randv3(seed) + randv3(seed + 10) * float3(.08, .02, .08) * t) * 
        float3(1, .1, Resolution.y / Resolution.x) + float3(0, .11, 0);
}

/* This runs like randOrigin, but for the camera's lookAt target, which is always
on the floor.
*/
float3 randLookAt(uint seed, float t)
{
    return (randv3(seed) + randv3(seed + 20) * float3(.08, 0, .08) * t) * 
        float3(1, 0, Resolution.y / Resolution.x) + float3(0, 0, 0);
}

/* Make the two cameras. We quantize the running time into discrete cycle-counts
that increment each time we change the camera's position. That becomes a steady
integer value that changes every n seconds, which makes for a good random seed
for values that should change every n seconds like camera position and target.
Since the cameras' on-times overlap in the transitions, the seeds have to change
at various phases in the run cycle.
Within a run cycle, we scoot the camera position and lookAt vectors by a little
bit, for a nice presentation.
Each camera does the usual correction to the up vector to line things up vertically.
*/
void makeCameras()
{
    int c = 0;
    int seed = int((Time + GAZE_TIME) / CYCLE_TIME);
    float t = ((Time + GAZE_TIME) / CYCLE_TIME) % 1;
    cameras[c].ray.origin = randOrigin(seed, t);
    float3 lookAt = randLookAt(seed + 8, t);
    cameras[c].up = float3(0, 1, 0);
    cameras[c].ray.dir = normalize(lookAt - cameras[c].ray.origin);
    cameras[c].left = cross(cameras[c].ray.dir, cameras[c].up);
    cameras[c].up = cross(cameras[c].left, cameras[c].ray.dir);

    c = 1;
    seed = int((Time + HALFCYCLE_TIME + GAZE_TIME) / CYCLE_TIME);
    t = ((Time + HALFCYCLE_TIME + GAZE_TIME) / CYCLE_TIME) % 1;
    cameras[c].ray.origin = randOrigin(seed + 3, t);
    lookAt = randLookAt(seed + 4, t);
    cameras[c].up = float3(0, 1, 0);
    cameras[c].ray.dir = normalize(lookAt - cameras[c].ray.origin);
    cameras[c].left = cross(cameras[c].ray.dir, cameras[c].up);
    cameras[c].up = cross(cameras[c].left, cameras[c].ray.dir);
}

/* Geometry helper for line-plane intersections. Returns true if the line hits the
plane, and if it did, d contains the distance to the plane. If we return true, then
d is always positive.
*/
bool hitPlane(Ray ray, PlaneRect rect, out float d)
{
    float rds = dot(ray.dir, rect.normal);
    if (rds != 0)
    {
        d = dot(rect.p0 - ray.origin, rect.normal) / rds;
        if (d > 0)
        {
            return true;
        }
    }
    return false;
}


/* Do some geometry to determine whether we hit a planerect. If we did, return true
and d will contain the distance to the hit point, and coords will contain the u, v
coordinates of the planerect at that point. If we return true, then d is always
positive, and coords is always in range (0, 1), good for sampling a texture.
*/
bool hitPlaneRect(Ray ray, PlaneRect rect, out float d, out float2 coords)
{
    if (hitPlane(ray, rect, d))
    {
        float3 p = ray.origin + ray.dir * d;
        float cx = dot(p - rect.p0, rect.p1 - rect.p0) / dot(rect.p1 - rect.p0, rect.p1 - rect.p0);
        float cy = dot(p - rect.p0, rect.p2 - rect.p0) / dot(rect.p2 - rect.p0, rect.p2 - rect.p0);
        coords = float2(cx, cy);
        return cx >= 0 && cx <= 1 && cy >= 0 && cy <= 1;
    }
    return false;
}

/* Do some geometry to determine whether we hit a sphere. If we did, return true
and d will contain the distance to the hit point. Returns false if we start inside
or in front of the sphere.
*/
bool hitSphere(Ray ray, Sphere sph, out float d)
{
        float3 omp = ray.origin - sph.p;
        float fdd = dot(ray.dir, omp);
        float del = fdd * fdd - (dot(omp, omp) - sph.r * sph.r);
        if (del < 0)
            { return false; }

        // cross the sphere twice (unless d0 == d1)
        float d0 = - fdd + sqrt(del);
        float d1 = - fdd - sqrt(del);
        // doesn't matter, just get the smallest (lesst positive or most negative) one
        d = d0;
        if (d1 < d)
            { d = d1; }

        // hit it if it's in front
        return d > 0;
}

float3 getSphereNormal(Sphere sph, float3 p)
{
    return normalize(p - sph.p);
}

/* This wacky thing tries to make soft shadows happen. It's not terribly accurate,
but it's what's for dinner. Some vague thing about how close the view and surface 
normal are to orthogonal, and modulated further by how close the shadowing object is
to p compated to how close the light is to p, scaled up as a hand-tune to improve the
effect. It's okay, not super.
*/
float canSeeLight(int l, float3 p)
{
    Light light = lights[l];
    Ray ray;
    ray.dir = normalize(light.p - p);
    ray.origin = p - 0.0001 * ray.dir;  // back p off a little
    for (int s = 0; s < NUM_SPHERES; ++s)
    {
        float d; // don't care
        if (hitSphere(ray, spheres[s], d))
        {
            float3 sp = ray.origin + ray.dir * d;
            float3 n = getSphereNormal(spheres[s], sp);
            float sh = dot(n, - ray.dir);   // range (0, 1)
            if (sh < .4)
            {
                // pow for effect
                sh = pow((1 - sh / .4), 2); // range 1, 1
                sh *= d / length(light.p - ray.origin);
                sh *= 20 / DIM_EFFECT / LIGHT_INTENSITY;
                return sh;
            }
            else
            {
                return 0;
            }
        }
    }

    return 1;
}

/* This isn't a really pro-grade shader. :) But it's nice for our use. Each light
can contribute to the overall shade.

Diffuse light is n.l * light color * material color. There's a soft shadow factor
as well.

Specular light is (n.h)^s * light color * material color * a smoothness factor. I'm
not sure this is cannonical bp shading, but it looks nice.

In both cases, the light contribution is modulated further by a soft shadow attempt.
The color is added, with the a channel signifying how much 'room' is left in the color
for further shading by reflections. Basically, if enough shine is on the surface, we
stop reflecting rays. It feels clumsy and ham-fisted, and I'd like to improve this.
*/
float4 shadeSurface(Ray ray, float3 p, float3 n, int material)
{
    float4 color = float4(0, 0, 0, 0);
    Material mat = materials[material];

    //  for ecah light:
    for (int l = 0; l < NUM_LIGHTS; ++l)
    {
        float softShadowFactor = canSeeLight(l, p);
        if (softShadowFactor == 0)
            { continue; }

        float light = float4(0, 0, 0, 0);

        // diffuse light
        float3 ptol = lights[l].p - p;
        float3 ptoln = normalize(ptol);
        float ndl = dot(n, ptoln);
        float distToLight2 = dot(ptol, ptol);
        if (ndl > 0)
        {
            color += softShadowFactor                           // soft shadow blend (0, 1)
                   * ndl                                        // n . l             (0, 1)
                   * float4(mat.diffuseColor, 1)                // material color    (0, 1) per channel
                   / distToLight2                               // 1 / d^2           (0, <1) per channel in our case; all lights are far away
                   * lights[l].color;                           // light color       (0, n) lights are hdr; a == 1
        }

        // specular light
        float3 ptoo = - ray.dir;
        float3 h = normalize(ptoo + ptoln);
        float hdn = dot(h, n);
        float hdnp = pow(hdn, mat.specularPower);
        if (hdn > 0)
        {
           color += softShadowFactor
                  * hdnp                                        // specular power
                  / distToLight2                                // 1 / d^2
                  * (   mat.smoothness * float4(1, 1, 1, 1)
                      + (1 - mat.smoothness) * float4(mat.diffuseColor, 1)
                    )
                  * lights[l].color;                            // light color
        }
    }

    return color;
}

/* Shade the sky according to how close we are aiming the view vector
to each light. And scale for tuning.
*/
float4 shadeSky(Ray ray)
{
    float4 color = float4(0, 0, 0, 1);
    for (int l = 0; l < NUM_LIGHTS; ++l)
    {
        float3 otol = normalize(lights[l].p - ray.origin);
        color.rgb += dot(ray.dir, otol) * lights[l].color / 10 / LIGHT_INTENSITY * SKY_INTENSITY;
    }
    return color;
}

/* Called if ray intersects the sphere. We just return a surface shade, bearing
in mind that the spheres are mostly reflective.
*/
float4 getSphereColor(Ray ray, Sphere sph, float3 p)
{
    float3 n = getSphereNormal(sph, p);
    return shadeSurface(ray, p, n, 1);
}

/* Called if ray intersects the planerect in-bounds. We are given the screen 
coords at the intersection point.
The desired effect is bright circles of pixel color light on a dark background.
I'm shooting for accuracy here, and there's an important caveat: The samplerState
set by the terminal app is set to use linear filtering, and is not overrideable.
So before sampling a texel's color, we quantize the sampling coords to texel 
granularity and get the color there. There will be no contribution from neighboring
texels to the color. (We actually need to offset by half a texel as well.)
Then we modulate that based on how far we had to move the sample coords to quanize
them (up to half a texel's width in u and v); this can modulate the brightness of
the texel color.
Then, because some of a texel's area is colorful and some is dark, we up the 
brightness of the color to compensate.
This is all for the emissive component. There's also the surface shading which is
added at the end.
*/
float4 getPlaneRectColor(Ray ray, PlaneRect rect, float3 p, float2 screenCoords)
{
    // quantize hit point to avoid linear filter
    float2 quantScreenCoords = screenCoords - modul((screenCoords), (1 / Resolution)); // quantize to resolution granularity
    quantScreenCoords += .5 / Resolution;  // bias for center-of-texel sampling

    // how much we moved to quantize determines texel brightness
    float2 falloff = (quantScreenCoords - screenCoords) * Resolution * 2;
    float falloffMag = clamp(1 - length(falloff), 0, 1);

    float4 color = float4(shaderTexture.Sample(samplerState, modul(quantScreenCoords, 1)).rgb * falloffMag, 1);
    color.rgb *= 2;     // brighter because dots
    color.rgb *= SCREEN_INTENSITY;

    // add light effect from diffuse surface
    color += shadeSurface(ray, p, screen.normal, 0);

    return color;
}

/* Cameras transform 2D sample coordinates into 3D view rays for raymarching.
samplePt is the u, v coords for sampling the view space similar to texture
coords, and ptidx is a value from 0 - 3, specifying which of four rays to
return. This is for antialiasing; tl, tr, bl, br. Pass -1 as ptidx to cancel
antialiasing, and just punch the center.
*/
Ray makeCameraRay(int camera, float2 samplePt, int ptidx)
{
    // First, scale the sample point to the aspect ratio, so we're at uniform
    // scale in x and y.
    float aspectRatio = Resolution.y / Resolution.x;
    float2 scaledSamplePt = samplePt - float2(0.5, 0.5);  // (-0.5, 0.5)
    scaledSamplePt *= float2(2, -2);      // (-1, 1), and invert y
    scaledSamplePt.y *= aspectRatio;   // scale extents

    if (ptidx == 0 || ptidx == 2)
        { scaledSamplePt.x -= 1 / (2 * Resolution.x); }
    else if (ptidx == 1 || ptidx == 3)
        { scaledSamplePt.x += 1 / (2 * Resolution.x); }

    if (ptidx == 0 || ptidx == 1)
        { scaledSamplePt.y += 1 / (2 * Resolution.x); }  // res.x is correct; we've already scaled
    else if (ptidx == 2 || ptidx == 3)
        { scaledSamplePt.y -= 1 / (2 * Resolution.x); }  // res.x is correct

    // Now make the ray by pointing forward, and nudging the look-at point 
    // horizontally and vertically by the scale-corrected sample address.
    // We also scale the effect more (/2) to get a nice field of view.
    Camera c = cameras[camera];
    Ray ray;
    ray.origin = c.ray.origin;
    ray.dir = normalize(c.ray.dir
                      + scaledSamplePt.x * (- c.left) / 2
                      + scaledSamplePt.y * c.up / 2);

    return ray;
}

/* Raymarching stuff. This is specialized to our scene, where predictable things 
happen: We can bounce around a bunch of mirror spheres, until we stop hitting 
spheres. Then we've hit the floor or sky, neither of which reflect. Whatever
light effect has accumulated on the spheres is then added to the sky or screen
color.

I'd like to improve this to be more generic, and handle reflections based on
material properties, and accumulate color in a better way.
*/
float4 fireRay(Ray ray)
{
    const int NUM_BOUNCES = 8;
    float4 bounceColor = float4(0, 0, 0, 0);

    for (int b = 0; b < NUM_BOUNCES && bounceColor.a < 1; ++b)
    {
        int best = -1;
        float bestd = 100;
        for (int i = 0; i < NUM_SPHERES; ++i)
        {
            Sphere sph = spheres[i];
            float d;
            if (hitSphere(ray, sph, d))
            {
                if (d > 0 && d < bestd)
                {
                    best = i;
                    bestd = d;
                }
            }
        }

        // we hit any sphere
        if (best >= 0)
        {
            Sphere sph = spheres[best];
            float d = bestd;
            float3 p = ray.origin + ray.dir * d;
            float3 ptoo = - ray.dir;
            float3 n = getSphereNormal(sph, p);

            bounceColor += getSphereColor(ray, sph, p);

            // reflect off the surface
            float3 refl = 2 * dot(n, ptoo) * n - ptoo;

            // reorient the ray
            ray.origin = p + 0.00001 * refl;  // nudge p outside the sphere.
            ray.dir = refl;
        }
    }

    // get screen hit point
    float2 screenCoords;
    float d;
    if (hitPlaneRect(ray, screen, d, screenCoords))
    {
        float3 p = ray.origin + ray.dir * d;
        float3 n = screen.normal;

        // get light - diffuse and low spec
        bounceColor.rgb += (1 - bounceColor.a) * getPlaneRectColor(ray, screen, p, screenCoords).rgb;
    }
    else
    {
        bounceColor.rgb += (1 - bounceColor.a) * shadeSky(ray).rgb;
    }
    bounceColor.a = 1;

    return bounceColor;
}

/* This is the start of the actual effect. Here we raymarch. We establish the
objects in our scene, and then run two cameras, fading between each. The cameras
fire a 3D view ray for the given sample point.
*/
float4 getEffectPixel(float2 samplePt)
{
    makeScreen();
    makeSpheres();
    makeLights();
    makeMaterials();
    makeCameras();

    float4 color = float4(0, 0, 0, 0);

    float f;
    // The cycle is divided up into four segments:
    // 0: cam0 on; cam1 off
    // 1: transitioning between cam0 and cam1
    // 2: cam0 off; cam1 on
    // 3: transitioning between cam1 and cam0
    float cycleTime = Time % CYCLE_TIME;    // range (0, CYCLE_TIME)
    if (cycleTime < GAZE_TIME)
    {
        f = 1;
    }
    else if (cycleTime < HALFCYCLE_TIME)
    {
        // using the front half of a cosine curve to go from 1 to 0
        f = cos((cycleTime - GAZE_TIME) / (2 * FADE_TIME) * TAU) / 2 + 0.5;
    }
    else if (cycleTime < (HALFCYCLE_TIME + GAZE_TIME))
    {
        f = 0;
    }
    else
    {
        // using the back half (+ tau/2) of a cosine curve to go from 0 to 1
        f = cos((cycleTime - (HALFCYCLE_TIME + GAZE_TIME)) / (2 * FADE_TIME) * TAU + TAU / 2) / 2 + 0.5;
    }

    // Calling this four times makes the shader compile take muy much long. :(
    // The run time is fine on my 2070.

    if (ANTIALIASING)
    {
        if (f != 0) // I don't know that this predication affects performance in shaderland.
        {
            // Unrolled loop actually shaves seconds off the compile time.
            Ray ray = makeCameraRay(0, samplePt, 0);
            color += fireRay(ray) * f * .25;
            ray = makeCameraRay(0, samplePt, 1);
            color += fireRay(ray) * f * .25;
            ray = makeCameraRay(0, samplePt, 2);
            color += fireRay(ray) * f * .25;
            ray = makeCameraRay(0, samplePt, 3);
            color += fireRay(ray) * f * .25;
        }

        if (f != 1) // This one neither nor.
        {
            // Unrolled loop actually shaves seconds off the compile time.
            Ray ray = makeCameraRay(1, samplePt, 0);
            color += fireRay(ray) * (1 - f) * .25;
            ray = makeCameraRay(1, samplePt, 1);
            color += fireRay(ray) * (1 - f) * .25;
            ray = makeCameraRay(1, samplePt, 2);
            color += fireRay(ray) * (1 - f) * .25;
            ray = makeCameraRay(1, samplePt, 3);
            color += fireRay(ray) * (1 - f) * .25;
        }
    }
    else
    {
        if (f != 0) // I don't know that this predication affects performance in shaderland.
        {
            Ray ray = makeCameraRay(0, samplePt, -1);
            color += fireRay(ray) * f;
        }

        if (f != 1) // This one neither nor.
        {
            Ray ray = makeCameraRay(1, samplePt, -1);
            color += fireRay(ray) * (1 - f);
        }
    }

    return color;
}

/* Main displays the sampled pixel if it has color, i.e. if alpha > 0. It also checks
its neighbors for any alpha value as well, to create a border around text. This 
involves eight more samples, placed around our texel position (tex uv). We can actually
sample four pixels at once by sampling at their intersection, and letting the linear
sampling filter add them all up. So we sample in an offset checker pattern, sampling at 
the intersection of neighboring texels and using the linear filter to determine if any
of those have any alpha component.

If we're clear of any text, pass through to getEffectPixel(), and mute that by 1/4.
*/
float4 main(float4 position : SV_POSITION, float2 tex : TEXCOORD) : SV_TARGET
{
    float4 inputColor = shaderTexture.Sample(samplerState, tex);
    // get samples around tex to test for opacity
    float2 texPerPixel = 1 / Resolution;
    float4 surrounds = shaderTexture.Sample(samplerState, tex + texPerPixel * float2(-1.5, -0.5))
                     + shaderTexture.Sample(samplerState, tex + texPerPixel * float2( 0.5, -1.5))
                     + shaderTexture.Sample(samplerState, tex + texPerPixel * float2(-0.5,  1.5))
                     + shaderTexture.Sample(samplerState, tex + texPerPixel * float2( 1.5,  0.5));

                     + shaderTexture.Sample(samplerState, tex + texPerPixel * float2(-1.5, -2.5))
                     + shaderTexture.Sample(samplerState, tex + texPerPixel * float2( 2.5, -1.5))
                     + shaderTexture.Sample(samplerState, tex + texPerPixel * float2(-2.5,  1.5))
                     + shaderTexture.Sample(samplerState, tex + texPerPixel * float2( 1.5,  2.5));
    if (surrounds.a > 0)
        { return inputColor; }

    return float4(DIM_EFFECT, DIM_EFFECT, DIM_EFFECT, 1) * getEffectPixel(tex);
}

