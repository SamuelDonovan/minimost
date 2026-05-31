/**
 * Tests for audio-processor.js
 *
 * audio-processor.js runs inside an AudioWorklet thread where
 * AudioWorkletProcessor is a global and registerProcessor is a global.
 * We mock both before loading the script.
 */

const { loadScript } = require('./loadScript');

let registered = null;
let processorPort;

beforeAll(() => {
    // Set up the AudioWorklet thread globals
    global.AudioWorkletProcessor = class {
        constructor() {
            processorPort = { postMessage: jest.fn() };
            this.port = processorPort;
        }
    };
    global.currentTime  = 0;
    global.sampleRate   = 48000;
    global.registerProcessor = jest.fn((name, cls) => {
        registered = { name, cls };
    });

    loadScript('audio-processor.js');
});

describe('audio-processor.js — registerProcessor', () => {
    test('calls registerProcessor with "audio-capture-processor"', () => {
        expect(global.registerProcessor).toHaveBeenCalledWith(
            'audio-capture-processor',
            expect.any(Function)
        );
        expect(registered).not.toBeNull();
        expect(registered.name).toBe('audio-capture-processor');
    });
});

describe('AudioCaptureProcessor — process()', () => {
    let proc;

    beforeEach(() => {
        const Proc = registered.cls;
        proc = new Proc();
    });

    test('returns true', () => {
        const result = proc.process([[new Float32Array(128).fill(0.5)]]);
        expect(result).toBe(true);
    });

    test('does not post when fewer than 4096 samples accumulated', () => {
        const input = new Float32Array(128).fill(0.1);
        proc.process([[input]]);
        expect(proc.port.postMessage).not.toHaveBeenCalled();
    });

    test('posts a message when exactly 4096 samples have been accumulated', () => {
        const input = new Float32Array(128).fill(0.1);
        // 32 * 128 = 4096
        for (let i = 0; i < 32; i++) {
            proc.process([[input]]);
        }
        expect(proc.port.postMessage).toHaveBeenCalledTimes(1);
        const posted = proc.port.postMessage.mock.calls[0][0];
        expect(posted).toBeInstanceOf(Float32Array);
        expect(posted.length).toBe(4096);
    });

    test('posts buffer slice (copy), not the internal buffer', () => {
        const input = new Float32Array(128).fill(0.5);
        for (let i = 0; i < 32; i++) proc.process([[input]]);
        const posted = proc.port.postMessage.mock.calls[0][0];
        expect(posted.every(v => v === 0.5)).toBe(true);
    });

    test('resets position after posting and accumulates further', () => {
        const input = new Float32Array(128).fill(0.2);
        for (let i = 0; i < 32; i++) proc.process([[input]]); // fills and posts once
        proc.port.postMessage.mockClear();

        // one more partial frame — no post yet
        proc.process([[input]]);
        expect(proc.port.postMessage).not.toHaveBeenCalled();

        // fill another full 4096
        for (let i = 0; i < 31; i++) proc.process([[input]]);
        expect(proc.port.postMessage).toHaveBeenCalledTimes(1);
    });

    test('handles multiple small frames accumulating correctly', () => {
        const small = new Float32Array(64).fill(0.3);
        // 64 * 64 = 4096
        for (let i = 0; i < 64; i++) proc.process([[small]]);
        expect(proc.port.postMessage).toHaveBeenCalledTimes(1);
    });

    test('handles no input channel gracefully (returns true)', () => {
        // inputs[0] is undefined
        const result = proc.process([[]]);
        expect(result).toBe(true);
        expect(proc.port.postMessage).not.toHaveBeenCalled();
    });

    test('handles completely empty inputs array (returns true)', () => {
        const result = proc.process([]);
        expect(result).toBe(true);
    });

    test('posts exactly twice after 8192 samples in one batch', () => {
        // 8192 = two full buffers, but we go frame-by-frame to trigger exact crossings
        const input = new Float32Array(128).fill(0.1);
        for (let i = 0; i < 64; i++) proc.process([[input]]);
        expect(proc.port.postMessage).toHaveBeenCalledTimes(2);
    });

    test('sample values are preserved correctly in posted buffer', () => {
        const input = new Float32Array(128);
        for (let i = 0; i < 128; i++) input[i] = i / 128;
        // Fill 32 frames where the last frame is unique
        const flat = new Float32Array(128).fill(0.5);
        for (let i = 0; i < 31; i++) proc.process([[flat]]);
        proc.process([[input]]);
        const posted = proc.port.postMessage.mock.calls[0][0];
        // The last 128 samples should be 0..127/128
        for (let i = 0; i < 128; i++) {
            expect(posted[3968 + i]).toBeCloseTo(i / 128);
        }
    });
});
