using System;

namespace Masters2026
{
    /// <summary>
    /// Emulates controlling a microphone.
    /// </summary>
    internal class MicrophoneEmulator
    {
        /// <summary>
        /// Backing field for the <see cref="Level"/> property.
        /// </summary>
        private ushort level;

        /// <summary>
        /// Backing field for the <see cref="Mute"/> property.
        /// </summary>
        private bool mute;

        /// <summary>
        /// Initializes a new instance of the <see cref="MicrophoneEmulator"/> class.
        /// </summary>
        /// <param name="label">The label to be used for the microphone.</param>
        internal MicrophoneEmulator(string label)
        {
            this.Label = label;

            Random rnd = new();
            this.Level = (ushort)rnd.Next(0, ushort.MaxValue + 1);
        }

        /// <summary>
        /// Occurs when the state of the microphone changes.
        /// </summary>
        public event EventHandler<MicrophoneEventArgs> MicrophoneChanged;

        /// <summary>
        /// Gets the label for the microphones.
        /// </summary>
        public string Label { get; private set; }

        /// <summary>
        /// Gets or sets the level for the microphone.
        /// </summary>
        public ushort Level
        {
            get
            {
                return this.level;
            }

            set
            {
                if (this.level != value)
                {
                    this.level = value;
                    this.MicrophoneChanged?.Invoke(this, new MicrophoneEventArgs(this));
                }
            }
        }

        /// <summary>
        /// Gets or sets a value indicating whether the microphone is muted.
        /// </summary>
        public bool Mute
        {
            get
            {
                return this.mute;
            }

            set
            {
                if (this.mute != value)
                {
                    this.mute = value;
                    this.MicrophoneChanged?.Invoke(this, new MicrophoneEventArgs(this));
                }
            }
        }
    }
}
