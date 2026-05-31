class AudioCaptureProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this._buf = new Float32Array(4096);
        this._pos = 0;
    }

    process(inputs) {
        const input = inputs[0]?.[0];
        if (!input) return true;
        for (let i = 0; i < input.length; i++) {
            this._buf[this._pos++] = input[i];
            if (this._pos >= 4096) {
                this.port.postMessage(this._buf.slice(0));
                this._pos = 0;
            }
        }
        return true;
    }
}

registerProcessor("audio-capture-processor", AudioCaptureProcessor);
