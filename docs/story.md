# How DOOM ended up running on a one-instruction language

<!-- The human story behind the repo. HTML comments mark numbers to re-check against
     docs/ship-gate.md before each public link; they do not render on GitHub. -->

**TL;DR:** FlipJump is a language I created that has only one instruction: flip a bit in memory,
then jump to the next instruction. This is the story of how I got DOOM running on it, in simple
terms.

I have dreamed of running a game on my FlipJump language for about five years. A year and a half
ago I showed myself (and posted on Hacker News) that any C code can be compiled into FlipJump,
which made it theoretically possible.

At that point I decided to take a break from developing FlipJump. It had been a long project to
build, and as much as I enjoyed it, I had reached the "ultimate" result and had no need to go
further. I also had many more ideas, but each one would take a lot of time from my real life, so I
decided to give it a rest.

That lasted until June this year. I had already put it behind me, but then I attended a friend's
lecture about how he got DOOM running on his home water dispenser, and it lit me up. I had also
started using Claude around that time, and I got a burst of motivation: I could actually make it
happen in a few months of work. Maybe. If only I could harness this tool to really understand
FlipJump, and turn my super-long-project idea into something that could be done.

## A few things you should know first

### What is FlipJump

```c
/* flipjump/interpreter/_fjcore.c, paraphrased for 32-bit words; addresses are bit addresses */
ip = 0;
for (;;) {
    f = mem[ip];                        /* read the flip word */
    mem[f >> 5] ^= 1u << (f & 31);      /* flip one bit       */
    ip = mem[ip + 1];                   /* jump               */
}
```

### What is DOOM

(Well, you wouldn't be here if you didn't know.) A 1993 game that revolutionized gaming, and in
recent years it has become a kind of modern achievement to run it on anything. Its engine source
has been open since 1997, and there are free, open replacements for its levels and art.

I use Freedoom's level and art, not id's: id Software's assets are still copyrighted and cannot be
redistributed, and I wanted anyone to be able to download the game. So what you will play is a
DOOM engine running Freedoom's first level.

### How do we start?

The obvious question: DOOM's C source is open, and I can compile C into FlipJump. FlipJump can
read input as "which keys are pressed right now" and can output "the next pixel's colour", so with
a very simple display device it can show a game.

So I looked into that, but there is a truth we cannot avoid. FlipJump flips bits. Even with my
C-to-FlipJump compiler as optimized as I could make it, the result would be a really slow game.
My FlipJump interpreter at that time ran at most a few million FlipJump ops per second, and each
C line compiled into several assembly instructions, each of which compiled into about 100 to
10,000 FlipJump ops. <!-- VERIFY: the 100 to 10,000 range -->

I did make the interpreter much faster while developing fjdoom, and reached 200M FlipJump ops per
second on my laptop. <!-- the shipped record (blocked63): 232.6M on one pinned core, blocked63_msframe_freeze.log --> But that
does not change the truth that compiled C cannot be optimized that far.

DOOM had to be written in FlipJump itself. And it would be A LOT of FlipJump lines. And it would
need EVERY OPTIMIZATION IT COULD GET.

"Written in FlipJump" does not mean typed by hand. The final program is 52 million words; its
FlipJump source is millions of lines. <!-- VERIFY: 2.8M lines on the previous build; re-count for
blocked53 --> A Python program I wrote generates it, the way a compiler would: it reads the level
from the WAD, compiles the BSP tree, textures, sprites and light tables into FlipJump data and
code, and expands the game logic through the standard library's macros. Python runs once, at build
time. At play time, only the loop above runs.

### Getting the tools ready

First, my FlipJump interpreter needed to be much faster and to have a better debugger. Most of
this was in issues I had opened and left in the backlog back in 2024 and 2025. Here Claude came in
very handy. Instead of spending several days per feature, I managed to ship ideas I had already
decided I would never have time for. I did not compromise on quality, and I did rough code reviews
myself to keep the FlipJump project's standards.

Changing code in the interpreter and the assembler was easy. Making Claude understand FlipJump, so
that it could review, check and write working FlipJump code, was not. I ran an iterative process:
it wrote hundreds of FlipJump programs, used the assembler, interpreter and debugger by itself, and
I reviewed it at every chance I got so it would write better code. That process produced a skill,
improved with every iteration, that the entire DOOM effort then ran on:
https://fjdocs.tomhe.app/tools/claude-skill.html. I decided the skill was good enough after it had
written about 1,000 working FlipJump programs.

I will say it plainly: without Claude I would never have done this project. It saved so much time
on every mini-mission that it made the whole thing possible. It also made it possible to open the
online interpreter (https://fj.tomhe.app) and the docs site (https://fjdocs.tomhe.app). Yet I did
not allow it to change things freely in the flipjump repository, which I have built for years to a
very high standard, so everything there went through human code review. In the doom-flipjump
repository I was more permissive.

## So, how is the game built?

### First, lowering our standards

I had wished for a game running at 320x200 at 25 fps. The math does not check out.

Let's see what we have. I can run about 200M FlipJump ops per second, so for 25 fps I can spend at
most about 8M ops per frame. 8M / (320 x 200) is 125 FlipJump ops per pixel.

That might sound like enough, so let me give you some perspective. I have a heavily optimized
standard library of FlipJump code that builds real functionality out of bit flips. Adding two
32-bit numbers takes about 800 FlipJump ops, and I doubt it can go much lower. Assigning x = y for
one-byte variables costs about 100 ops on its own. So 125 ops per pixel is not enough.

Lowering our standards: I would allocate about 15M ops per frame (about 13 fps) and a 160x100
screen. That is about 940 FlipJump ops per pixel, barely one addition. If that still sounds
impossible, I agreed with you, and every signal I got at the start said exactly that.

### WAIT. I understand the high-level stuff, but how do you actually DO anything in FlipJump?

Fair question, and an important one. If you are already a bit familiar, feel free to skip to the
next section.

A FlipJump instruction has two arguments, a flip address (F) and a jump address (J), written
`F;J`. It flips the F-th bit in memory, then fetches the next instruction, which starts at the J-th
bit in memory. No load. No store. The power of the language comes from self-modification.

Assume the instruction at address 0x100 is `0;FUNC1` and the instruction at 0x140 is `0;FUNC2`
(FUNC1 and FUNC2 being labels of other addresses). Say you have some memory location labelled
VARIABLE that holds the instruction `0;0`.

If the program executes the instruction `VARIABLE+0x28;VARIABLE`, it modifies the VARIABLE
instruction into `0;0x100` and then jumps to it, so you end up at address 0x100, and from there at
the code at FUNC1.

BUT if VARIABLE initially held `0;0x40`, the same instruction turns it into `0;0x140`, jumps to it,
and you land at address 0x140, and so at the code at FUNC2.

Notice that the VARIABLE instruction was used as an actual variable, and we just built an "if" on
it. That is the very basis of FlipJump programming: instructions double as memory, memory values
steer the flow of the program, and the memory keeps changing as the program runs.

(The arithmetic, for the curious: an instruction is 64 bits and its jump address is the upper 32,
so bit 0x28 = 40 is bit 8 of the jump address, and flipping it adds 0x100.)

And I did manage to build an open-source library of every piece of functionality that came to
mind, as macros that can be used throughout FlipJump development.

### Starting up

Now you see why I saw magic in this language. Once I had a working skill, a faster FlipJump and a
goal, I spent a net 10 to 20 hours talking with Claude, planning how the thing would go. FlipJump
has optimization tricks I know best from writing the standard library, and I wanted all of them
used: lots of lookup tables, and everything possible built on ifs, xors and constants. I also made
sure the skill knew how to search the standard library rather than reinvent the wheel.

Debugging bit flips is brutal, so I improved the debugger, but the real answer was better than a
debugger: I planned to build the same game in Python too, so that testing meant checking that the
Python game and the FlipJump game match pixel for pixel in every frame.

That Python twin, the "oracle", became the project's law. Every change to the FlipJump side has to
reproduce the oracle's frame byte for byte, with the instruction count equal to the digit, on a
fixed set of viewpoints and scripted games, before it is accepted. A single pixel off fails the
build. This is also what let me hand so much implementation to an AI: it did not have to be
trusted, only to pass.

At first the goal was not a game loop but rendering single frames as cheaply as possible. So I
first built the frame renderer, which, given fixed constants (x, y, viewing angle), drew one frame.

Then came the first working frame.

It was magnificent.

And it cost about 1B FlipJump ops. 1,000,000,000. About 0.2 fps. Without any game logic. Nice.
<!-- the record: 1,165,180,455 ops, docs/m13d2-perf-findings.md -->

I understood that Claude could not optimize from the intuition I had built up over the years. So
came a long phase of testing ideas, benchmarks to tell the good ideas from the bad, reading up on
fast software rendering, and digging into the generated code to find unoptimized parts. And it
worked. I lowered the graphics a notch and got to 25M FlipJump ops per frame.
<!-- 1B: 1,165,180,455 (docs/m13d2-perf-findings.md); 25M: no record found, the base renderer was 28.19M (docs/handoff-perf.md) -- owner to confirm or change -->

The goal looked achievable now.

### A playable game!

So I had a fast single-frame renderer. Now for the game loop. To get a full game I built the loop,
read keyboard input, added walking (x, y and viewing angle change with the keys) and collision with
walls.

At that stage the game loop cost about +10M, for a total of 35M ops per frame. I found more
optimizations as before, in both the graphics and the loop, and by now, with many worked examples
from me, Claude managed to find more on its own. I got it to about 24M ops per frame.
<!-- records: 35.29M (M14.5), 24.31M (docs/handoff-perf.md) -->

Then came doors and lifts, and static monsters and items. I could walk the whole first level and
everything was static, but it worked. I played it for a while, collected everything that felt
wrong, and fixed it. The game felt playable.

Finally came moving monsters, damage taken from monsters, shooting at monsters with six weapons on five
keys, up to a rocket launcher, dying, a health and ammo bar, a main menu, a help page and a map. With Claude finding more optimizations along the way, the
shipped game measures:

* Binary size: 39.8 MB (52.3M 32-bit memory words, compressed)
* Mean FlipJump ops per frame: 16.1M on the benchmark tours, 14.2M in the frozen combat scenarios <!-- blocked62: gamespeed mean 16,076,977, (mean+p80)/2 16,837,730; v10 combat mean 14,193,897 -->
* Screen: 160x100, about 15 fps (68 ms per frame on one pinned core, 233M flip-jumps per second)

![Where a frame's flip-jumps go, and what the 52M-word program is made of](media/blocked62_pies.png)

*Left: the 16.1M flip-jumps of a mean frame of the benchmark tours. Walls take 60%, sprites 24%,
floors and ceilings 6%, the BSP walk 5.5%; all the game logic, the status bar and the menus together
are 1.6%. Right: the 52.1M-word program. Lookup tables are 41% of it, which is the whole trick:
arithmetic is read, not computed. Measured on blocked62 (M7 P13).*

### Thanks

I am genuinely grateful for the AI's help here. I know it is not common to thank these kinds of
tools, especially for advances in theoretical subjects. I believe I could have done every part of
it myself, but it would have taken a few years, and so I probably would never have gotten to it.
With these tools (and about 25B tokens <!-- VERIFY -->) and about four months, I turned this dream
into reality.

### Perspective

I do not take this result for granted. It is insanely optimized, and here is the comparison that
shows it.

Forget modern GPUs; a GPU spends tens of thousands of floating-point operations on every pixel of
a modern game, and comparing that to DOOM is apples to oranges. Compare apples to apples instead:
DOOM itself, in 1993.

DOOM ran on a 486DX2-66, a chip rated at 54 MIPS. In the game's own timedemo that machine renders
about 25 to 30 frames per second. That is on the order of two million instructions per frame, about
thirty instructions for every one of the 64,000 pixels at 320x200. And each of those instructions
is a real instruction: one of them adds two 32-bit numbers.

fjdoom spends about 900 flip-jumps per pixel in a fight (14.2 million a frame over 16,000 pixels).
Adding two 32-bit numbers costs about 800 of them.

Read that again. Every textured, shaded, perspective-correct pixel on the screen is drawn for about
the price of one addition. The whole frame, monsters, fireballs and all, costs about as much
flipping as eighteen thousand additions. id Software had two million instructions to spend on the
same job.

How is that even possible? Because almost nothing is computed; it is looked up. The level's BSP
tree is compiled into code. The arithmetic lives in tables placed in memory so that reading an
answer is the same act as flipping the next jump address. The frame does not calculate its way to
a pixel; it jumps there.

(The 486 figures are enthusiasts' timedemo measurements, and Dhrystone MIPS flatters a chip that
spends much of a DOOM frame waiting on memory. Both errors make the 486 look busier than it was,
so the real gap is smaller than the arithmetic says. The point survives: thirty instructions per
pixel against one addition's worth of flips.)

That is the power of getting to know the bits and bytes of an architecture, and understanding how
to use it best.

That is probably the end of my journey with FlipJump, at least for a while, and I hope it gives you
the motivation to start that project you have been waiting for.

---

Try it:

```bash
pip install "flipjump[io]"
curl -LO https://github.com/tomhea/doom-flipjump/releases/latest/download/doom.fjm
fj --run doom.fjm
```

Also possible, with nothing to install: `uvx fjdoom`. (Until the 1.0 release is out none of these
lines works yet: flipjump 1.6.0 is not on PyPI, the release file does not exist and the `fjdoom`
package is not published; see docs/developing.md to build it.) The code is at
https://github.com/tomhea/doom-flipjump, and the numbers, each with the command that produced it,
are in [ship-gate.md](ship-gate.md).
