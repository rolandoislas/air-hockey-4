class Rect:
    def __init__(self, x, y, width, height):
        self.x = x if x >= 0 else 0
        self.y = y if y >= 0 else 0
        self.width = width
        self.height = height
        self.right = self.x + self.width / 2
        self.left = self.right - self.width
        self.top = self.y + self.height / 2
        self.bottom = self.top - self.height

    def overlaps(self, other):
        if self.left <= other.right and self.left >= other.left and self.bottom <= other.top \
                and self.top >= other.bottom:
            return True
        return False
