/**
 * Cognitia Audio Manager
 * Handles audio recording, playback, and real-time call audio
 * 
 * Implements circular buffer recording similar to the original Cognitia:
 * - Constantly records audio to a circular buffer
 * - Uses VAD (Voice Activity Detection) to detect speech
 * - Includes pre-activation buffer (captures audio before speech detected)
 * - Waits for pause after speech before sending
 */

export class AudioManager {
    constructor() {
        this.mediaRecorder = null;
        this.audioContext = null;
        this.analyser = null;
        this.mediaStream = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.isPlaying = false;
        this.audioQueue = [];
        this.currentSource = null;
        this.ownsMediaStreamTracks = false;
        this.sampleRate = 16000; // Match Cognitia sample rate
        
        // Call mode with circular buffer (like original Cognitia)
        this.inCall = false;
        this.scriptProcessor = null;
        
        // Circular buffer settings (matching Cognitia)
        this.VAD_SIZE = 32;      // ms per VAD chunk (512 samples at 16kHz)
        this.BUFFER_SIZE = 800;  // ms of pre-activation buffer
        this.PAUSE_LIMIT = 640;  // ms of silence before processing
        
        // VAD settings
        this.vadThreshold = 0.02;  // RMS threshold for voice detection
        this.vadSmoothingWindow = 3; // Number of chunks to smooth VAD
        this.vadHistory = [];
        
        // Circular buffer for pre-activation audio
        this.circularBuffer = [];
        this.maxBufferChunks = Math.floor(this.BUFFER_SIZE / this.VAD_SIZE); // ~25 chunks
        
        // Recording state
        this.recordingStarted = false;
        this.samples = [];
        this.gapCounter = 0;
        this.pauseChunks = Math.floor(this.PAUSE_LIMIT / this.VAD_SIZE); // ~20 chunks
        
        // Callbacks
        this.onAudioReady = null;
        this.onVadStatus = null;
    }

    async init() {
        this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: this.sampleRate
        });
        return this;
    }

    async startRecording() {
        if (this.isRecording) return;

        try {
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: this.sampleRate,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true
                }
            });

            this.audioChunks = [];
            this.mediaRecorder = new MediaRecorder(this.mediaStream, {
                mimeType: 'audio/webm;codecs=opus'
            });

            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };

            this.mediaRecorder.start(100); // Collect every 100ms
            this.isRecording = true;
            console.log('Recording started');
            return true;
        } catch (error) {
            console.error('Failed to start recording:', error);
            return false;
        }
    }

    async stopRecording() {
        if (!this.isRecording || !this.mediaRecorder) return null;

        return new Promise((resolve) => {
            this.mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
                
                // Convert to base64
                const reader = new FileReader();
                reader.onloadend = () => {
                    const base64 = reader.result.split(',')[1];
                    resolve({
                        data: base64,
                        format: 'webm-opus',
                        sampleRate: this.sampleRate
                    });
                };
                reader.readAsDataURL(audioBlob);

                // Clean up
                this.mediaStream.getTracks().forEach(track => track.stop());
                this.isRecording = false;
            };

            this.mediaRecorder.stop();
        });
    }

    async playAudio(audioData, format = 'wav') {
        if (!this.audioContext) await this.init();

        try {
            let audioBuffer;

            if (format === 'pcm' || format === 'raw') {
                // Handle raw PCM data (16-bit signed, mono)
                const pcmData = this.base64ToArrayBuffer(audioData);
                audioBuffer = await this.decodePCM(pcmData);
            } else {
                // Handle encoded formats (wav, mp3, etc.)
                const arrayBuffer = this.base64ToArrayBuffer(audioData);
                audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
            }

            // Queue the audio
            this.audioQueue.push(audioBuffer);
            
            // Start playback if not already playing
            if (!this.isPlaying) {
                this.playNextInQueue();
            }
        } catch (error) {
            console.error('Failed to play audio:', error);
        }
    }

    async playNextInQueue() {
        if (this.audioQueue.length === 0) {
            this.isPlaying = false;
            return;
        }

        this.isPlaying = true;
        const audioBuffer = this.audioQueue.shift();

        this.currentSource = this.audioContext.createBufferSource();
        this.currentSource.buffer = audioBuffer;
        this.currentSource.connect(this.audioContext.destination);

        this.currentSource.onended = () => {
            this.playNextInQueue();
        };

        this.currentSource.start();
    }

    stopPlayback() {
        if (this.currentSource) {
            this.currentSource.stop();
            this.currentSource = null;
        }
        this.audioQueue = [];
        this.isPlaying = false;
    }

    async decodePCM(arrayBuffer) {
        const samples = new Int16Array(arrayBuffer);
        const floats = new Float32Array(samples.length);
        
        for (let i = 0; i < samples.length; i++) {
            floats[i] = samples[i] / 32768.0;
        }

        const audioBuffer = this.audioContext.createBuffer(1, floats.length, this.sampleRate);
        audioBuffer.getChannelData(0).set(floats);
        return audioBuffer;
    }

    base64ToArrayBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    // Real-time call mode
    async startCallMode(onAudioChunk) {
        if (this.inCall) return;

        try {
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: this.sampleRate,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true
                }
            });

            if (!this.audioContext) await this.init();

            const source = this.audioContext.createMediaStreamSource(this.mediaStream);
            const processor = this.audioContext.createScriptProcessor(4096, 1, 1);
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 512;

            this.ownsMediaStreamTracks = true;

            source.connect(this.analyser);
            this.analyser.connect(processor);
            processor.connect(this.audioContext.destination);

            // Store callback
            this.onAudioReady = onAudioChunk;
            
            // Reset state for new call
            this.resetCallState();

            // Calculate chunk size: VAD_SIZE ms at sampleRate
            const vadChunkSize = Math.floor(this.sampleRate * this.VAD_SIZE / 1000); // 512 samples at 16kHz

            processor.onaudioprocess = (event) => {
                const inputData = event.inputBuffer.getChannelData(0);
                
                // Process in VAD_SIZE chunks (like Cognitia)
                for (let offset = 0; offset < inputData.length; offset += vadChunkSize) {
                    const chunk = inputData.slice(offset, offset + vadChunkSize);
                    if (chunk.length < vadChunkSize) continue;
                    
                    // Convert to Float32Array copy
                    const sample = new Float32Array(chunk);
                    
                    // Calculate VAD confidence (RMS-based, like Silero VAD output)
                    const vadConfidence = this.calculateVadConfidence(sample);
                    
                    // Handle audio sample (same logic as Cognitia SpeechListener)
                    this.handleAudioSample(sample, vadConfidence);
                }
            };

            this.scriptProcessor = processor;
            this.inCall = true;
            console.log('Call mode started with circular buffer');
            return true;
        } catch (error) {
            console.error('Failed to start call mode:', error);
            return false;
        }
    }

    /**
     * Start call-mode volume metering using an existing MediaStream.
     * Intended for LiveKit/WebRTC where mic is already captured elsewhere.
     */
    async startCallMeterFromStream(mediaStream) {
        if (!mediaStream) return false;

        try {
            if (!this.audioContext) await this.init();

            // Clean up any previous nodes without stopping external tracks.
            if (this.scriptProcessor) {
                this.scriptProcessor.disconnect();
                this.scriptProcessor = null;
            }

            this.mediaStream = mediaStream;
            this.ownsMediaStreamTracks = false;

            const source = this.audioContext.createMediaStreamSource(this.mediaStream);
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 512;

            source.connect(this.analyser);
            this.inCall = true;
            return true;
        } catch (error) {
            console.error('Failed to start call meter:', error);
            return false;
        }
    }

    /**
     * Reset call state for a new call session
     */
    resetCallState() {
        this.circularBuffer = [];
        this.samples = [];
        this.recordingStarted = false;
        this.gapCounter = 0;
        this.vadHistory = [];
    }

    /**
     * Calculate VAD confidence using RMS with smoothing
     * Returns true if voice activity detected
     */
    calculateVadConfidence(sample) {
        // Calculate RMS
        let sum = 0;
        for (let i = 0; i < sample.length; i++) {
            sum += sample[i] * sample[i];
        }
        const rms = Math.sqrt(sum / sample.length);
        
        // Add to history for smoothing
        this.vadHistory.push(rms);
        if (this.vadHistory.length > this.vadSmoothingWindow) {
            this.vadHistory.shift();
        }
        
        // Average RMS over window
        const avgRms = this.vadHistory.reduce((a, b) => a + b, 0) / this.vadHistory.length;
        
        // Update VAD status callback
        if (this.onVadStatus) {
            this.onVadStatus(avgRms > this.vadThreshold, avgRms);
        }
        
        return avgRms > this.vadThreshold;
    }

    /**
     * Handle audio sample - implements Cognitia SpeechListener logic
     * Routes processing based on recording state
     */
    handleAudioSample(sample, vadConfidence) {
        if (!this.recordingStarted) {
            this.managePreActivationBuffer(sample, vadConfidence);
        } else {
            this.processActivatedAudio(sample, vadConfidence);
        }
    }

    /**
     * Manage circular pre-activation buffer
     * When voice detected, start recording with buffer contents
     */
    managePreActivationBuffer(sample, vadConfidence) {
        // Add to circular buffer (automatically handles overflow via maxBufferChunks)
        this.circularBuffer.push(sample);
        if (this.circularBuffer.length > this.maxBufferChunks) {
            this.circularBuffer.shift();
        }
        
        if (vadConfidence) {
            // Voice detected! Start recording
            // Copy circular buffer contents to samples (includes audio before detection)
            this.samples = [...this.circularBuffer];
            this.recordingStarted = true;
            this.gapCounter = 0;
            console.log('Voice detected, started recording with', this.samples.length, 'pre-buffer chunks');
        }
    }

    /**
     * Process audio after voice activation
     * Track silence gaps and process when pause detected
     */
    processActivatedAudio(sample, vadConfidence) {
        // Add sample to recording
        this.samples.push(sample);
        
        if (!vadConfidence) {
            // Silence detected
            this.gapCounter++;
            
            // Check if pause is long enough
            if (this.gapCounter >= this.pauseChunks) {
                this.processDetectedAudio();
            }
        } else {
            // Voice detected, reset gap counter
            this.gapCounter = 0;
        }
    }

    /**
     * Process completed speech segment and send to backend
     */
    processDetectedAudio() {
        if (this.samples.length === 0) {
            this.resetRecordingState();
            return;
        }
        
        console.log('Processing', this.samples.length, 'audio chunks');
        
        // Concatenate all samples
        const totalLength = this.samples.reduce((sum, s) => sum + s.length, 0);
        const combined = new Float32Array(totalLength);
        let offset = 0;
        for (const sample of this.samples) {
            combined.set(sample, offset);
            offset += sample.length;
        }
        
        // Normalize audio (like Cognitia ASR preprocessing)
        const maxVal = Math.max(...combined.map(Math.abs));
        if (maxVal > 0) {
            for (let i = 0; i < combined.length; i++) {
                combined[i] /= maxVal;
            }
        }
        
        // Convert to Int16 PCM for transmission
        const int16 = new Int16Array(combined.length);
        for (let i = 0; i < combined.length; i++) {
            int16[i] = Math.max(-32768, Math.min(32767, Math.floor(combined[i] * 32767)));
        }
        
        // Send to backend
        if (this.onAudioReady) {
            const base64 = this.arrayBufferToBase64(int16.buffer);
            this.onAudioReady(base64, 'pcm', this.sampleRate);
        }
        
        // Reset for next utterance
        this.resetRecordingState();
    }

    /**
     * Reset recording state but keep circular buffer running
     */
    resetRecordingState() {
        this.recordingStarted = false;
        this.samples = [];
        this.gapCounter = 0;
        // Note: circularBuffer keeps running for pre-activation
    }

    stopCallMode() {
        if (!this.inCall) return;

        if (this.scriptProcessor) {
            this.scriptProcessor.disconnect();
            this.scriptProcessor = null;
        }

        if (this.analyser) {
            try {
                this.analyser.disconnect();
            } catch {
                // ignore
            }
            this.analyser = null;
        }

        if (this.mediaStream) {
            if (this.ownsMediaStreamTracks) {
                this.mediaStream.getTracks().forEach(track => track.stop());
            }
            this.mediaStream = null;
        }

        this.ownsMediaStreamTracks = false;

        this.resetCallState();
        this.inCall = false;
        this.onAudioReady = null;
        this.onVadStatus = null;
        console.log('Call mode stopped');
    }

    getVolume() {
        if (!this.analyser) return 0;

        const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
        this.analyser.getByteFrequencyData(dataArray);
        
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
            sum += dataArray[i];
        }
        return sum / dataArray.length / 255;
    }
    
    /**
     * Check if currently recording speech
     */
    isRecordingSpeech() {
        return this.recordingStarted;
    }
    
    /**
     * Manually trigger processing of current audio (for interrupts)
     */
    forceProcess() {
        if (this.recordingStarted && this.samples.length > 0) {
            this.processDetectedAudio();
        }
    }

    isSupported() {
        return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    }
}
