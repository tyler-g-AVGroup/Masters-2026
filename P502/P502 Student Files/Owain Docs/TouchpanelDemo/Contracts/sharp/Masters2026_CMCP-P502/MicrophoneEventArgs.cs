using System;

namespace Masters2026
{
    /// <summary>
    /// Contains the state information for a microphone.
    /// </summary>
    internal class MicrophoneEventArgs : EventArgs
    {
        /// <summary>
        /// Initializes a new instance of the <see cref="MicrophoneEventArgs"/> class.
        /// </summary>
        /// <param name="microphone">An instance of <see cref="MicrophoneEmulator"/>.</param>
        internal MicrophoneEventArgs(MicrophoneEmulator microphone)
        {
            this.Label = microphone.Label;
            this.Level = microphone.Level;
            this.Mute = microphone.Mute;
        }

        /// <summary>
        /// Gets or sets the label for the microphone.
        /// </summary>
        public string Label { get; protected set; }

        /// <summary>
        /// Gets or sets the level of the microphone.
        /// </summary>
        public ushort Level { get; protected set; }

        /// <summary>
        /// Gets or sets a value indicating whether the microphone is muted.
        /// </summary>
        public bool Mute { get; protected set; }
    }
}
