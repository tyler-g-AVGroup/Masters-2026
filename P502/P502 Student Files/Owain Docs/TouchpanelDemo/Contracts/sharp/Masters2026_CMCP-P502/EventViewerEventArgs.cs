using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;

namespace Masters2026
{
    /// <summary>
    /// Contains a list of UI events.
    /// </summary>
    internal class EventViewerEventArgs : EventArgs
    {
        /// <summary>
        /// Initializes a new instance of the <see cref="EventViewerEventArgs"/> class.
        /// </summary>
        /// <param name="events">The list of UI events.</param>
        internal EventViewerEventArgs(List<EventItem> events)
        {
            this.Events = events.AsReadOnly();
        }

        /// <summary>
        /// Gets or sets a list of UI events.
        /// </summary>
        public ReadOnlyCollection<EventItem> Events { get; protected set; }
    }
}
