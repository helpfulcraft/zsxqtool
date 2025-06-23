document.addEventListener('DOMContentLoaded', () => {
    const topicButtons = document.querySelectorAll('.topic-filter .topic-tag');
    const tagButtons = document.querySelectorAll('.tag-filter .tag');
    const postCards = document.querySelectorAll('.post-card');

    let activeTopic = 'all';
    let activeTag = 'all';

    // 主题筛选事件
    topicButtons.forEach(button => {
        button.addEventListener('click', () => {
            const selectedTopic = button.dataset.topic;
            if (selectedTopic === activeTopic) return;

            topicButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            activeTopic = selectedTopic;
            applyFilters();
        });
    });

    // 标签筛选事件
    tagButtons.forEach(button => {
        button.addEventListener('click', () => {
            const selectedTag = button.dataset.tag;
            if (selectedTag === activeTag) return;
            
            tagButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            activeTag = selectedTag;
            applyFilters();
        });
    });

    function applyFilters() {
        postCards.forEach(card => {
            const cardTopic = card.dataset.topic;
            const cardTags = card.dataset.tags.split(',');

            const topicMatch = activeTopic === 'all' || cardTopic === activeTopic;
            const tagMatch = activeTag === 'all' || cardTags.includes(activeTag);

            if (topicMatch && tagMatch) {
                card.classList.remove('hidden');
            } else {
                card.classList.add('hidden');
            }
        });
    }
}); 